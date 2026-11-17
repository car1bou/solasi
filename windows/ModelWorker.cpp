#include "NativePlatform.hpp"
#include "llama.h"
#include "ggml-backend.h"
#include "common.h"
#include "chat.h"
#include "sampling.h"
#include "json-schema-to-grammar.h"
#include "mtmd.h"
#include "mtmd-helper.h"
#include <chrono>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
using json = common_json;
constexpr const char *engine_id = "llama.cpp-b11669/windows-cpu-qwen35-v1/chat-template-no-thinking-v1";
constexpr size_t max_input = 10*1024*1024;
constexpr size_t max_output = 8*1024*1024;

void require(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

json read_request() {
    unsigned char header[4]; std::cin.read(reinterpret_cast<char *>(header), 4);
    require(std::cin.gcount() == 4, "모델 요청 헤더 없음");
    uint32_t size = (uint32_t(header[0]) << 24) | (uint32_t(header[1]) << 16) | (uint32_t(header[2]) << 8) | header[3];
    require(size > 0 && size <= max_input, "모델 입력 크기 오류");
    std::string body(size, '\0'); std::cin.read(body.data(), size);
    require(size_t(std::cin.gcount()) == size, "모델 입력이 중단되었습니다");
    return json::parse(body);
}

bool write_reply(const json &reply) {
    auto body = reply.dump();
    if (body.size() > max_output) body = R"({"ok":false,"error":"직접 실행 응답 크기 오류"})";
    uint32_t size = uint32_t(body.size());
    unsigned char header[] = {uint8_t(size >> 24), uint8_t(size >> 16), uint8_t(size >> 8), uint8_t(size)};
    std::cout.write(reinterpret_cast<const char *>(header), 4); std::cout << body; std::cout.flush();
    return bool(std::cout);
}

int integer(const json &request, const char *key, int low, int high) {
    require(request.contains(key) && request[key].is_number_integer(), "모델 예산 형식 오류");
    auto value = request[key].get<int64_t>();
    require(value >= low && value <= high, "모델 예산 범위 오류");
    return int(value);
}

json generate(const json &request, const char *libraries) {
    require(request.is_object(), "모델 요청 형식 오류");
    int output_limit = integer(request, "output_limit", 1, 4096);
    int context_limit = integer(request, "context_limit", 512, 8192);
    require(request.contains("messages") && request["messages"].is_array() && !request["messages"].empty(), "모델 메시지 오류");
    require(request.contains("images") && request["images"].is_array() && request["images"].size() <= 4, "이미지 개수 오류");
    require(request.contains("view") && request["view"].is_string(), "모델 경로 오류");
    require(request.contains("schema") && (request["schema"].is_null() || request["schema"].is_object()), "출력 schema 오류");
    common_chat_templates_inputs inputs;
    size_t text_size = 0;
    int last_user = -1;
    for (const auto &row : request["messages"]) {
        require(row.is_object() && row.contains("role") && row["role"].is_string() && row.contains("content") && row["content"].is_string(), "모델 메시지 오류");
        common_chat_msg message; message.role = row["role"].get<std::string>(); message.content = row["content"].get<std::string>();
        require(message.role == "system" || message.role == "user" || message.role == "assistant", "모델 역할 오류");
        text_size += message.content.size(); require(text_size <= 4*1000000, "모델 메시지 크기 오류");
        if (message.role == "user") last_user = int(inputs.messages.size());
        inputs.messages.push_back(std::move(message));
    }
    auto root = std::filesystem::u8path(request["view"].get<std::string>());
    std::vector<std::vector<unsigned char>> image_data;
    for (const auto &entry : request["images"]) {
        require(entry.is_string(), "이미지 경로 오류");
        std::ifstream stream(std::filesystem::u8path(entry.get<std::string>()), std::ios::binary | std::ios::ate);
        require(bool(stream), "이미지 파일 오류");
        auto size = stream.tellg(); require(size >= 8 && size <= 20*1024*1024, "이미지 크기 오류");
        image_data.emplace_back(size_t(size)); stream.seekg(0);
        stream.read(reinterpret_cast<char *>(image_data.back().data()), size);
        require(bool(stream), "이미지 읽기 오류");
        const auto &data = image_data.back();
        require((data[0] == 0xff && data[1] == 0xd8 && data[2] == 0xff) ||
                std::string(reinterpret_cast<const char *>(data.data()), 8) == "\x89PNG\r\n\x1a\n", "PNG·JPEG 이미지만 지원합니다");
    }
    if (!image_data.empty()) {
        require(last_user >= 0, "이미지 질문 없음");
        auto &message = inputs.messages[size_t(last_user)];
        for (size_t i = 0; i < image_data.size(); ++i) message.content_parts.push_back({"media_marker", mtmd_default_marker()});
        message.content_parts.push_back({"text", message.content}); message.content.clear();
    }
    inputs.enable_thinking = false;
    inputs.chat_template_kwargs["enable_thinking"] = "false";
    inputs.force_pure_content = true;
    std::string schema_grammar;
    if (!request["schema"].is_null()) {
        inputs.json_schema = request["schema"].dump();
        schema_grammar = json_schema_to_grammar(request["schema"], true);
        require(!schema_grammar.empty(), "출력 schema grammar 생성 실패");
    }
    auto started = std::chrono::steady_clock::now();
    ggml_backend_load_all_from_path(libraries); llama_backend_init();
    auto params = llama_model_default_params(); params.n_gpu_layers = 0;
    std::unique_ptr<llama_model, decltype(&llama_model_free)> model(
        llama_model_load_from_file((root/"model.gguf").u8string().c_str(), params), llama_model_free);
    require(bool(model), "Qwen3.5 모델을 열 수 없습니다");
    auto config = llama_context_default_params();
    config.n_ctx = uint32_t(context_limit); config.n_batch = 512; config.n_ubatch = 128;
    config.n_threads = 4; config.n_threads_batch = 4; config.n_seq_max = 1;
    std::unique_ptr<llama_context, decltype(&llama_free)> context(llama_init_from_model(model.get(), config), llama_free);
    require(bool(context), "생성 context 초기화 실패");
    auto *vocab = llama_model_get_vocab(model.get());
    auto templates = common_chat_templates_init(model.get(), "");
    common_chat_session session(templates.get(), vocab, inputs);
    common_params_sampling sampling;
    sampling.temp = 0.0f; session.apply_sampling(sampling);
    // Pure-content chat rendering skips template grammar, so enforce the schema explicitly.
    if (!schema_grammar.empty()) {
        sampling.grammar = {COMMON_GRAMMAR_TYPE_USER, schema_grammar};
        sampling.grammar_lazy = false;
    }
    common_sampler_ptr sampler(common_sampler_init(model.get(), sampling));
    require(bool(sampler), "생성 sampler 초기화 실패");
    auto prompt = session.prompt().str();
    llama_pos past = 0; size_t prompt_tokens = 0;
    mtmd::context_ptr vision;
    mtmd::bitmaps bitmaps;
    if (!image_data.empty()) {
        auto vision_params = mtmd_context_params_default();
        vision_params.use_gpu = false; vision_params.n_threads = 4;
        vision_params.image_max_tokens = 1024;
        vision.reset(mtmd_init_from_file((root/"mmproj.gguf").u8string().c_str(), model.get(), vision_params));
        require(bool(vision) && mtmd_support_vision(vision.get()), "이미지 projector 초기화 실패");
        for (const auto &data : image_data) {
            auto decoded = mtmd_helper_bitmap_init_from_buf(vision.get(), data.data(), data.size(), false, mtmd_helper_init_opt_default());
            require(decoded.bitmap != nullptr, "이미지 해석 실패");
            bitmaps.entries.emplace_back(decoded.bitmap);
        }
        auto bitmap_ptrs = bitmaps.c_ptr();
        mtmd::input_chunks_ptr chunks(mtmd_input_chunks_init());
        mtmd_input_text text{prompt.data(), prompt.size(), true, true};
        require(mtmd_tokenize(vision.get(), chunks.get(), &text, bitmap_ptrs.data(), bitmap_ptrs.size()) == 0, "이미지 입력 tokenize 실패");
        prompt_tokens = mtmd_helper_get_n_tokens(chunks.get());
        require(prompt_tokens + size_t(output_limit) <= size_t(context_limit), "이미지 입력이 문맥 예산을 초과했습니다");
        require(mtmd_helper_eval_chunks(vision.get(), context.get(), chunks.get(), 0, 0, 512, true, &past) == 0, "이미지 입력 처리 실패");
    } else {
        auto tokens = common_tokenize(vocab, prompt, true, true); prompt_tokens = tokens.size();
        require(!tokens.empty() && tokens.size() + size_t(output_limit) <= size_t(context_limit), "입력이 문맥 예산을 초과했습니다");
        for (size_t offset = 0; offset < tokens.size(); offset += 512) {
            int count = int(std::min(size_t(512), tokens.size()-offset));
            auto batch = llama_batch_get_one(tokens.data()+offset, count);
            require(llama_decode(context.get(), batch) == 0, "입력 처리 실패"); past += count;
        }
    }
    auto loaded = std::chrono::steady_clock::now();
    common_chat_input output;
    bool stopped = false; int generated = 0;
    for (; generated < output_limit; ++generated) {
        auto token = common_sampler_sample(sampler.get(), context.get(), -1);
        common_sampler_accept(sampler.get(), token, true);
        if (llama_vocab_is_eog(vocab, token)) { stopped = true; break; }
        output.append(common_token_to_piece(vocab, token), token);
        require(output.size() <= max_output/2, "모델 출력 크기 초과");
        auto batch = llama_batch_init(1, 0, 1); batch.n_tokens = 1;
        batch.token[0] = token; batch.pos[0] = past++; batch.n_seq_id[0] = 1; batch.seq_id[0][0] = 0; batch.logits[0] = true;
        int result = llama_decode(context.get(), batch); llama_batch_free(batch);
        require(result == 0, "생성 decode 실패");
    }
    auto message = session.finish(output);
    auto elapsed = [](auto a, auto b) { return std::chrono::duration<double, std::milli>(b-a).count(); };
    return {{"text", message.content}, {"finish_reason", stopped ? "stop" : "length"},
            {"usage", {{"prompt_eval_count", prompt_tokens}, {"eval_count", generated},
                       {"timings_ms", {{"model_load_prefill_ms", elapsed(started, loaded)},
                                        {"inference_ms", elapsed(loaded, std::chrono::steady_clock::now())}}}}}};
}
}

int worker_main(int argc, char **argv) {
#ifdef _WIN32
    solasi::binary_stdio();
#else
    std::signal(SIGPIPE, SIG_IGN);
#endif
    std::ios::sync_with_stdio(false);
    try {
        require(argc >= 2, "private library 경로 없음");
        if (argc == 3 && std::string(argv[2]) == "--check") {
            return write_reply({{"ok", true}, {"result", {{"engine", engine_id}}}}) ? 0 : 2;
        }
        auto reply = generate(read_request(), argv[1]);
        return write_reply({{"ok", true}, {"result", reply}}) ? 0 : 2;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        write_reply({{"ok", false}, {"error", error.what()}}); return 2;
    }
}

#ifdef _WIN32
int wmain(int argc, wchar_t **argv) { return solasi::utf8_main(argc, argv, worker_main); }
#else
int main(int argc, char **argv) { return worker_main(argc, argv); }
#endif
