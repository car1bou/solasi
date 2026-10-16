#pragma once
#include "llama.h"
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace solasi {
// Mapping follows Ollama's MIT-licensed handle_embeddinggemma; see docs/embedding-worker.md.
struct EmbeddingSource {
    struct Tensor { size_t offset; size_t size; };
    int fd = -1;
    void *mapping = MAP_FAILED;
    size_t size = 0;
    std::unordered_map<std::string, Tensor> tensors;
    ~EmbeddingSource() { if (mapping != MAP_FAILED) munmap(mapping, size); if (fd >= 0) close(fd); }
};

inline void set_embedding_tensor(ggml_tensor *tensor, void *userdata) {
    auto &source = *static_cast<EmbeddingSource *>(userdata);
    std::string name = tensor->name;
    auto entry = source.tensors.find(name == "output.weight" ? "token_embd.weight" : name);
    if (entry == source.tensors.end()) {
        // The public user loader allocates optional biases/scales; their neutral values preserve BF16 math.
        if (tensor->type == GGML_TYPE_F32 && name.size() > 5 && name.compare(name.size()-5, 5, ".bias") == 0) {
            std::vector<float> zeros(ggml_nelements(tensor), 0);
            ggml_backend_tensor_set(tensor, zeros.data(), 0, ggml_nbytes(tensor)); return;
        }
        bool scale = (name.size() > 6 && name.compare(name.size()-6, 6, ".scale") == 0) ||
                     (name.size() > 12 && name.compare(name.size()-12, 12, ".input_scale") == 0);
        if (tensor->type == GGML_TYPE_F32 && ggml_nelements(tensor) == 1 && scale) {
            float one = 1; ggml_backend_tensor_set(tensor, &one, 0, sizeof(one)); return;
        }
        throw std::runtime_error("unsupported embedding tensor");
    }
    auto data = entry->second;
    if (data.size != ggml_nbytes(tensor) || data.offset > source.size || data.size > source.size-data.offset)
        throw std::runtime_error("embedding tensor boundary mismatch");
    ggml_backend_tensor_set(tensor, static_cast<unsigned char *>(source.mapping)+data.offset, 0, data.size);
}

inline llama_model *load_embedding(const char *path, llama_model_params params) {
    EmbeddingSource source;
    source.fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    struct stat info{};
    if (source.fd < 0 || fstat(source.fd, &info) || !S_ISREG(info.st_mode) || info.st_size != 621867104)
        throw std::runtime_error("unsupported embedding model file");
    source.size = size_t(info.st_size);
    source.mapping = mmap(nullptr, source.size, PROT_READ, MAP_PRIVATE, source.fd, 0);
    if (source.mapping == MAP_FAILED) throw std::runtime_error("embedding model mapping failed");
    int read_fd = dup(source.fd);
    if (read_fd < 0) throw std::runtime_error("embedding model read failed");
    std::unique_ptr<FILE, decltype(&fclose)> file(fdopen(read_fd, "rb"), fclose);
    if (!file) { close(read_fd); throw std::runtime_error("embedding model read failed"); }
    ggml_context *parsed = nullptr;
    std::unique_ptr<gguf_context, decltype(&gguf_free)> original(gguf_init_from_file_ptr(file.get(), {true, &parsed}), gguf_free);
    std::unique_ptr<ggml_context, decltype(&ggml_free)> tensors(parsed, ggml_free);
    if (!original || !tensors) throw std::runtime_error("embedding GGUF parse failed");
    auto arch = gguf_find_key(original.get(), "general.architecture");
    if (arch < 0 || gguf_get_kv_type(original.get(), arch) != GGUF_TYPE_STRING ||
            std::string(gguf_get_val_str(original.get(), arch)) != "gemma3" || gguf_get_n_tensors(original.get()) != 316)
        throw std::runtime_error("unsupported embedding architecture");
    auto *d0 = ggml_get_tensor(tensors.get(), "dense.0.weight");
    auto *d1 = ggml_get_tensor(tensors.get(), "dense.1.weight");
    auto *tokens = ggml_get_tensor(tensors.get(), "token_embd.weight");
    if (!d0 || !d1 || !tokens || d0->ne[0] != 768 || d0->ne[1] != 3072 ||
            d1->ne[0] != 3072 || d1->ne[1] != 768 || tokens->ne[0] != 768 || tokens->ne[1] != 262144)
        throw std::runtime_error("unsupported embedding dimensions");
    std::unique_ptr<gguf_context, decltype(&gguf_free)> meta(gguf_init_empty(), gguf_free);
    gguf_set_kv(meta.get(), original.get());
    gguf_set_val_str(meta.get(), "general.architecture", "gemma-embedding");
    for (int64_t i = 0; i < gguf_get_n_kv(original.get()); i++) {
        std::string key = gguf_get_key(original.get(), i);
        if (key.rfind("gemma3.", 0) != 0) continue;
        key = "gemma-embedding." + key.substr(7);
        if (key == "gemma-embedding.attention.causal" || key == "gemma-embedding.attention.sliding_window_pattern") continue;
        switch (gguf_get_kv_type(original.get(), i)) {
            case GGUF_TYPE_UINT32: gguf_set_val_u32(meta.get(), key.c_str(), gguf_get_val_u32(original.get(), i)); break;
            case GGUF_TYPE_FLOAT32: gguf_set_val_f32(meta.get(), key.c_str(), gguf_get_val_f32(original.get(), i)); break;
            default: throw std::runtime_error("unsupported embedding metadata");
        }
    }
    gguf_set_val_f32(meta.get(), "gemma-embedding.rope.freq_base_swa", 10000);
    gguf_set_val_u32(meta.get(), "gemma-embedding.dense_2_feat_in", 768);
    gguf_set_val_u32(meta.get(), "gemma-embedding.dense_2_feat_out", 3072);
    gguf_set_val_u32(meta.get(), "gemma-embedding.dense_3_feat_in", 3072);
    gguf_set_val_u32(meta.get(), "gemma-embedding.dense_3_feat_out", 768);
    auto base = gguf_get_data_offset(original.get());
    for (int64_t i = 0; i < gguf_get_n_tensors(original.get()); i++) {
        std::string name = gguf_get_tensor_name(original.get(), i);
        auto *tensor = ggml_get_tensor(tensors.get(), name.c_str());
        if (!tensor) throw std::runtime_error("embedding tensor missing");
        if (name == "dense.0.weight") name = "dense_2.weight";
        if (name == "dense.1.weight") name = "dense_3.weight";
        ggml_set_name(tensor, name.c_str()); gguf_add_tensor(meta.get(), tensor);
        auto offset = gguf_get_tensor_offset(original.get(), i);
        if (base > source.size || offset > source.size-base) throw std::runtime_error("embedding offset overflow");
        source.tensors.emplace(name, EmbeddingSource::Tensor{base+offset, gguf_get_tensor_size(original.get(), i)});
    }
    ggml_set_name(tokens, "output.weight"); gguf_add_tensor(meta.get(), tokens);
    return llama_model_init_from_user(meta.get(), set_embedding_tensor, &source, params);
}
}
