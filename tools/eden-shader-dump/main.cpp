// SPDX-FileCopyrightText: Copyright 2026 EdEn.claude
// SPDX-License-Identifier: GPL-3.0-or-later

// eden-shader-dump: offline inspection of an Eden Vulkan guest shader cache (vulkan.bin).
//
// For every pipeline in the cache it re-runs Eden's shader recompiler on each guest shader and
// writes, per unique shader hash:
//   <hash>.<stage>.ir    Eden IR after all optimisation passes
//   <hash>.<stage>.spv   SPIR-V as Eden would emit it (generic profile, see below)
// plus index.tsv: pipeline hash, stage hashes, texture handle -> pixel format of each shader.
//
// Usage: eden-shader-dump <vulkan.bin> <out_dir>

#include <array>
#include <cstring>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <map>
#include <set>
#include <string>
#include <vector>

#include <ankerl/unordered_dense.h>
#include <fmt/format.h>

#include "common/common_funcs.h"
#include "common/common_types.h"
#include "shader_recompiler/backend/bindings.h"
#include "shader_recompiler/backend/spirv/emit_spirv.h"
#include "shader_recompiler/environment.h"
#include "shader_recompiler/exception.h"
#include "shader_recompiler/frontend/ir/program.h"
#include "shader_recompiler/frontend/maxwell/control_flow.h"
#include "shader_recompiler/frontend/maxwell/translate_program.h"
#include "shader_recompiler/host_translate_info.h"
#include "shader_recompiler/object_pool.h"
#include "shader_recompiler/profile.h"
#include "shader_recompiler/runtime_info.h"

namespace {

constexpr std::array<char, 8> MAGIC_NUMBER{'y', 'u', 'z', 'u', 'c', 'a', 'c', 'h'};
constexpr u32 CACHE_VERSION = 17;               // vk_pipeline_cache.cpp
constexpr size_t GRAPHICS_KEY_SIZE = 1048;      // sizeof(Vulkan::GraphicsPipelineCacheKey), arm64
constexpr size_t COMPUTE_KEY_SIZE = 24;         // sizeof(Vulkan::ComputePipelineCacheKey), arm64

u64 MakeCbufKey(u32 index, u32 offset) {
    return (static_cast<u64>(index) << 32) | offset;
}

// Mirror of VideoCommon::FileEnvironment (video_core/shader_environment.cpp).
class DumpEnvironment final : public Shader::Environment {
public:
    void Deserialize(std::ifstream& file) {
        u64 code_size{}, num_texture_types{}, num_texture_pixel_formats{}, num_cbuf_values{},
            num_cbuf_replacement_values{};
        file.read(reinterpret_cast<char*>(&code_size), sizeof(code_size))
            .read(reinterpret_cast<char*>(&num_texture_types), sizeof(num_texture_types))
            .read(reinterpret_cast<char*>(&num_texture_pixel_formats),
                  sizeof(num_texture_pixel_formats))
            .read(reinterpret_cast<char*>(&num_cbuf_values), sizeof(num_cbuf_values))
            .read(reinterpret_cast<char*>(&num_cbuf_replacement_values),
                  sizeof(num_cbuf_replacement_values))
            .read(reinterpret_cast<char*>(&local_memory_size), sizeof(local_memory_size))
            .read(reinterpret_cast<char*>(&texture_bound), sizeof(texture_bound))
            .read(reinterpret_cast<char*>(&start_address), sizeof(start_address))
            .read(reinterpret_cast<char*>(&read_lowest), sizeof(read_lowest))
            .read(reinterpret_cast<char*>(&read_highest), sizeof(read_highest))
            .read(reinterpret_cast<char*>(&viewport_transform_state),
                  sizeof(viewport_transform_state))
            .read(reinterpret_cast<char*>(&stage), sizeof(stage));
        code.resize((code_size + sizeof(u64) - 1) / sizeof(u64));
        file.read(reinterpret_cast<char*>(code.data()), code_size);
        for (size_t i = 0; i < num_texture_types; ++i) {
            u32 key;
            Shader::TextureType type;
            file.read(reinterpret_cast<char*>(&key), sizeof(key))
                .read(reinterpret_cast<char*>(&type), sizeof(type));
            texture_types.emplace(key, type);
        }
        for (size_t i = 0; i < num_texture_pixel_formats; ++i) {
            u32 key;
            Shader::TexturePixelFormat format;
            file.read(reinterpret_cast<char*>(&key), sizeof(key))
                .read(reinterpret_cast<char*>(&format), sizeof(format));
            texture_pixel_formats.emplace(key, format);
        }
        for (size_t i = 0; i < num_cbuf_values; ++i) {
            u64 key;
            u32 value;
            file.read(reinterpret_cast<char*>(&key), sizeof(key))
                .read(reinterpret_cast<char*>(&value), sizeof(value));
            cbuf_values.emplace(key, value);
        }
        for (size_t i = 0; i < num_cbuf_replacement_values; ++i) {
            u64 key;
            Shader::ReplaceConstant value;
            file.read(reinterpret_cast<char*>(&key), sizeof(key))
                .read(reinterpret_cast<char*>(&value), sizeof(value));
            cbuf_replacements.emplace(key, value);
        }
        if (stage == Shader::Stage::Compute) {
            file.read(reinterpret_cast<char*>(&workgroup_size), sizeof(workgroup_size))
                .read(reinterpret_cast<char*>(&shared_memory_size), sizeof(shared_memory_size));
        } else {
            file.read(reinterpret_cast<char*>(&sph), sizeof(sph));
            if (stage == Shader::Stage::Geometry) {
                file.read(reinterpret_cast<char*>(&gp_passthrough_mask),
                          sizeof(gp_passthrough_mask));
            }
        }
        is_proprietary_driver = texture_bound == 2;
    }

    u64 ReadInstruction(u32 address) override {
        if (address < read_lowest || address > read_highest) {
            throw Shader::LogicError("Out of bounds address {}", address);
        }
        return code[(address - read_lowest) / sizeof(u64)];
    }
    u32 ReadCbufValue(u32 cbuf_index, u32 cbuf_offset) override {
        const auto it{cbuf_values.find(MakeCbufKey(cbuf_index, cbuf_offset))};
        if (it == cbuf_values.end()) {
            throw Shader::LogicError("Uncached cbuf value");
        }
        return it->second;
    }
    Shader::TextureType ReadTextureType(u32 handle) override {
        const auto it{texture_types.find(handle)};
        if (it == texture_types.end()) {
            throw Shader::LogicError("Uncached texture type");
        }
        return it->second;
    }
    Shader::TexturePixelFormat ReadTexturePixelFormat(u32 handle) override {
        const auto it{texture_pixel_formats.find(handle)};
        if (it == texture_pixel_formats.end()) {
            throw Shader::LogicError("Uncached texture pixel format");
        }
        return it->second;
    }
    bool IsTexturePixelFormatInteger(u32 handle) override {
        // Integer formats sit between these PixelFormat values; good enough for inspection.
        (void)ReadTexturePixelFormat(handle);
        return false;
    }
    u32 ReadViewportTransformState() override {
        return viewport_transform_state;
    }
    u32 TextureBoundBuffer() const override {
        return texture_bound;
    }
    u32 LocalMemorySize() const override {
        return local_memory_size;
    }
    u32 SharedMemorySize() const override {
        return shared_memory_size;
    }
    std::array<u32, 3> WorkgroupSize() const override {
        return workgroup_size;
    }
    bool HasHLEMacroState() const override {
        return !cbuf_replacements.empty();
    }
    std::optional<Shader::ReplaceConstant> GetReplaceConstBuffer(u32 bank, u32 offset) override {
        const auto it = cbuf_replacements.find(MakeCbufKey(bank, offset));
        if (it == cbuf_replacements.end()) {
            return std::nullopt;
        }
        return it->second;
    }
    void Dump(u64, u64) override {}

    const auto& PixelFormats() const {
        return texture_pixel_formats;
    }

private:
    std::vector<u64> code;
    ankerl::unordered_dense::map<u32, Shader::TextureType> texture_types;
    ankerl::unordered_dense::map<u32, Shader::TexturePixelFormat> texture_pixel_formats;
    ankerl::unordered_dense::map<u64, u32> cbuf_values;
    ankerl::unordered_dense::map<u64, Shader::ReplaceConstant> cbuf_replacements;
    std::array<u32, 3> workgroup_size{};
    u32 local_memory_size{};
    u32 shared_memory_size{};
    u32 texture_bound{};
    u32 read_lowest{};
    u32 read_highest{};
    u32 viewport_transform_state = 1;
};

const char* StageName(Shader::Stage stage) {
    switch (stage) {
    case Shader::Stage::VertexA:
        return "vsa";
    case Shader::Stage::VertexB:
        return "vs";
    case Shader::Stage::TessellationControl:
        return "tcs";
    case Shader::Stage::TessellationEval:
        return "tes";
    case Shader::Stage::Geometry:
        return "gs";
    case Shader::Stage::Fragment:
        return "fs";
    case Shader::Stage::Compute:
        return "cs";
    }
    return "unknown";
}

} // Anonymous namespace

int main(int argc, char** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s <vulkan.bin> <out_dir>\n", argv[0]);
        return 1;
    }
    const std::filesystem::path out_dir{argv[2]};
    std::filesystem::create_directories(out_dir);
    std::ifstream file(argv[1], std::ios::binary | std::ios::ate);
    if (!file) {
        std::fprintf(stderr, "cannot open %s\n", argv[1]);
        return 1;
    }
    const auto end{file.tellg()};
    file.seekg(0);
    std::array<char, 8> magic{};
    u32 version{};
    file.read(magic.data(), magic.size()).read(reinterpret_cast<char*>(&version), sizeof(version));
    if (magic != MAGIC_NUMBER || version != CACHE_VERSION) {
        std::fprintf(stderr, "bad magic or cache version %u\n", version);
        return 1;
    }

    // Host description close to an Xclipse with the EdEn.claude defaults (FP16 lowered).
    const Shader::HostTranslateInfo host_info{
        .support_float64 = false,
        .support_float16 = false,
        .support_int64 = true,
        .needs_demote_reorder = false,
        .support_snorm_render_buffer = true,
        .support_viewport_index_layer = true,
        .min_ssbo_alignment = 16,
        .max_per_stage_descriptor_sampled_images = 1024,
        .max_per_stage_resources = 1024,
        .max_descriptor_set_sampled_images = 4096,
        .support_geometry_shader_passthrough = false,
        .support_conditional_barrier = true,
    };
    Shader::Profile profile{};
    profile.supported_spirv = 0x00010500;
    profile.unified_descriptor_binding = true;
    profile.support_descriptor_aliasing = true;
    profile.support_int8 = true;
    profile.support_int16 = true;
    profile.support_int64 = true;
    profile.support_vertex_instance_id = false;
    profile.support_float_controls = true;
    profile.support_demote_to_helper_invocation = true;
    profile.support_derivative_control = true;
    profile.support_scaled_attributes = true;
    profile.support_typeless_image_loads = true;
    profile.support_native_ndc = true;
    profile.support_multi_viewport = true;
    profile.warp_size_potentially_larger_than_guest = true;
    profile.min_ssbo_alignment = 16;
    profile.max_user_clip_distances = 8;

    std::ofstream index(out_dir / "index.tsv");
    index << "kind\tpipeline\tstage\tshader_hash\tstatus\ttextures(handle:format)\n";
    std::set<u64> done;
    size_t pipelines = 0, shaders = 0, failures = 0;
    while (file.tellg() != end && file.good()) {
        u32 num_envs{};
        file.read(reinterpret_cast<char*>(&num_envs), sizeof(num_envs));
        std::vector<DumpEnvironment> envs(num_envs);
        for (auto& env : envs) {
            env.Deserialize(file);
        }
        const bool compute = !envs.empty() && envs.front().ShaderStage() == Shader::Stage::Compute;
        std::vector<char> key(compute ? COMPUTE_KEY_SIZE : GRAPHICS_KEY_SIZE);
        file.read(key.data(), key.size());
        std::array<u64, 6> hashes{};
        if (compute) {
            std::memcpy(hashes.data(), key.data(), sizeof(u64));
        } else {
            std::memcpy(hashes.data(), key.data(), sizeof(hashes));
        }
        ++pipelines;
        size_t hash_index = 0;
        for (auto& env : envs) {
            while (!compute && hash_index < hashes.size() && hashes[hash_index] == 0) {
                ++hash_index;
            }
            const u64 shader_hash = compute ? hashes[0] : hashes[hash_index++];
            std::string textures;
            for (const auto& [handle, format] : env.PixelFormats()) {
                textures += fmt::format("{:x}:{} ", handle, static_cast<u32>(format));
            }
            std::string status = "ok";
            if (done.insert(shader_hash).second) {
                try {
                    Shader::ObjectPool<Shader::IR::Inst> inst_pool;
                    Shader::ObjectPool<Shader::IR::Block> block_pool;
                    Shader::ObjectPool<Shader::Maxwell::Flow::Block> flow_pool;
                    const u32 cfg_offset = compute
                                               ? env.StartAddress()
                                               : env.StartAddress() +
                                                     static_cast<u32>(sizeof(Shader::ProgramHeader));
                    Shader::Maxwell::Flow::CFG cfg(env, flow_pool, cfg_offset,
                                                   env.ShaderStage() == Shader::Stage::VertexA);
                    auto program = Shader::Maxwell::TranslateProgram(inst_pool, block_pool, env,
                                                                     cfg, host_info);
                    const std::string base =
                        fmt::format("{:016x}.{}", shader_hash, StageName(env.ShaderStage()));
                    std::ofstream(out_dir / (base + ".ir")) << Shader::IR::DumpProgram(program);
                    if (env.ShaderStage() != Shader::Stage::VertexA) {
                        Shader::RuntimeInfo runtime_info{};
                        for (auto& type : runtime_info.generic_input_types) {
                            type = Shader::AttributeType::Float;
                        }
                        Shader::Backend::Bindings bindings;
                        const auto spirv =
                            Shader::Backend::SPIRV::EmitSPIRV(profile, runtime_info, program,
                                                              bindings);
                        std::ofstream(out_dir / (base + ".spv"), std::ios::binary)
                            .write(reinterpret_cast<const char*>(spirv.data()),
                                   spirv.size() * sizeof(u32));
                    }
                    ++shaders;
                } catch (const std::exception& e) {
                    status = fmt::format("error: {}", e.what());
                    ++failures;
                }
            } else {
                status = "dup";
            }
            index << (compute ? "compute" : "graphics") << '\t' << fmt::format("{:016x}", hashes[0] ^ hashes[5])
                  << '\t' << StageName(env.ShaderStage()) << '\t'
                  << fmt::format("{:016x}", shader_hash) << '\t' << status << '\t' << textures
                  << '\n';
        }
    }
    std::printf("pipelines=%zu shaders=%zu failures=%zu\n", pipelines, shaders, failures);
    return 0;
}
