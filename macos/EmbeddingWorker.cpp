#include "EmbeddingCompat.hpp"
#include "EmbeddingProtocol.hpp"
#include <cmath>
#include <csignal>
#include <iomanip>
#include <iostream>
#include <locale>
#include <sstream>

namespace {
bool error(const char *code, const char *message, bool fatal) {
    return solasi::write_frame(std::cout, std::string("{\"error\":{\"code\":\"")+code+
        "\",\"message\":\""+message+"\"},\"fatal\":"+(fatal ? "true}" : "false}"));
}
}

int main(int argc, char **argv) {
    std::signal(SIGPIPE, SIG_IGN);
    std::ios::sync_with_stdio(false);
    if (argc != 3) { error("arguments", "Model and private library paths are required", true); return 2; }
    try {
        ggml_backend_load_all_from_path(argv[2]); llama_backend_init();
        auto params = llama_model_default_params(); params.n_gpu_layers = 99;
        std::unique_ptr<llama_model, decltype(&llama_model_free)> model(solasi::load_embedding(argv[1], params), llama_model_free);
        if (!model) throw std::runtime_error("embedding model load failed");
        auto config = llama_context_default_params();
        config.n_ctx = 2048; config.n_batch = 2048; config.n_ubatch = 2048; config.n_seq_max = 1;
        config.embeddings = true; config.pooling_type = LLAMA_POOLING_TYPE_MEAN;
        config.n_threads = 4; config.n_threads_batch = 4;
        std::unique_ptr<llama_context, decltype(&llama_free)> context(llama_init_from_model(model.get(), config), llama_free);
        if (!context || llama_model_n_embd_out(model.get()) != 768 || llama_pooling_type(context.get()) != LLAMA_POOLING_TYPE_MEAN)
            throw std::runtime_error("embedding context initialization failed");
        if (!solasi::write_frame(std::cout, "{\"ready\":true,\"dim\":768,\"pooling\":\"mean\",\"context_tokens\":2048,\"engine\":\"llama.cpp-b11669/ollama-embeddinggemma-v1\"}")) return 0;
        auto *vocab = llama_model_get_vocab(model.get());
        std::string text;
        while (true) {
            auto state = solasi::read_frame(std::cin, text);
            if (state == solasi::FrameStatus::eof) return 0;
            if (state != solasi::FrameStatus::ok) {
                error(state == solasi::FrameStatus::oversize ? "frame_too_large" : "truncated_frame", "Invalid request frame", true); return 2;
            }
            auto valid = solasi::text_status(text);
            if (valid != solasi::TextStatus::valid) {
                if (!error(valid == solasi::TextStatus::empty ? "empty" : "invalid_utf8", "Nonempty UTF-8 text is required", false)) return 0;
                continue;
            }
            int count = -llama_tokenize(vocab, text.data(), int32_t(text.size()), nullptr, 0, true, false);
            if (count <= 0 || count > 2048) { if (!error("context_limit", "Input exceeds the model token limit", false)) return 0; continue; }
            std::vector<llama_token> tokens(count);
            if (llama_tokenize(vocab, text.data(), int32_t(text.size()), tokens.data(), count, true, false) != count)
                throw std::runtime_error("embedding tokenizer mismatch");
            auto batch = llama_batch_init(count, 0, 1); batch.n_tokens = count;
            for (int i = 0; i < count; i++) {
                batch.token[i] = tokens[i]; batch.pos[i] = i; batch.n_seq_id[i] = 1; batch.seq_id[i][0] = 0; batch.logits[i] = true;
            }
            if (auto memory = llama_get_memory(context.get())) llama_memory_clear(memory, true);
            int result = llama_model_has_encoder(model.get()) ? llama_encode(context.get(), batch) : llama_decode(context.get(), batch);
            llama_batch_free(batch);
            if (result != 0) throw std::runtime_error("embedding inference failed");
            auto *vector = llama_get_embeddings_seq(context.get(), 0);
            if (!vector) throw std::runtime_error("embedding output missing");
            double norm = 0;
            for (int i = 0; i < 768; i++) { if (!std::isfinite(vector[i])) throw std::runtime_error("embedding output is not finite"); norm += double(vector[i])*vector[i]; }
            if (!(norm > 0) || !std::isfinite(norm)) throw std::runtime_error("embedding output norm is invalid");
            norm = std::sqrt(norm);
            std::ostringstream reply; reply.imbue(std::locale::classic()); reply << std::setprecision(10);
            reply << "{\"tokens\":" << count << ",\"vector\":[";
            for (int i = 0; i < 768; i++) { if (i) reply << ','; reply << vector[i]/norm; }
            reply << "]}";
            if (!solasi::write_frame(std::cout, reply.str())) return 0;
        }
    } catch (const std::exception &exception) {
        std::cerr << exception.what() << '\n'; error("engine", "Embedding engine failed", true); return 3;
    }
}
