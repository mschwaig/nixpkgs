{
  stdenv,
  buildPackages,
  buildBazelPackage,
  fetchFromGitHub,
  lib,
}:
let
  buildPlatform = stdenv.buildPlatform;
  hostPlatform = stdenv.hostPlatform;
  pythonEnv = buildPackages.python312.withPackages (
    ps: with ps; [
      distutils
      numpy
    ]
  );
  bazelDepsSha256ByBuildAndHost = {
    x86_64-linux = {
      x86_64-linux = "sha256-hInf6KQ4N3sOTtklMkY2ATsOsHOnkfK1mSQGjxWqFZk=";
      aarch64-linux = "sha256-SxcI3dv7LCAgvuveIPs6wD3krRiotTDD08LrzXVAOWg=";
    };
    aarch64-linux = {
      aarch64-linux = "sha256-yU3efv7GUjQthPN88SXMwkUs2VEIy8s0poqy4KGJzyY=";
    };
  };
  bazelHostConfigName.aarch64-linux = "elinux_aarch64";
  bazelDepsSha256ByHost =
    bazelDepsSha256ByBuildAndHost.${buildPlatform.system}
      or (throw "unsupported build system ${buildPlatform.system}");
  bazelDepsSha256 =
    bazelDepsSha256ByHost.${hostPlatform.system}
      or (throw "unsupported host system ${hostPlatform.system} with build system ${buildPlatform.system}");
in
buildBazelPackage rec {
  name = "tensorflow-lite";
  version = "2.19.0";

  src = fetchFromGitHub {
    owner = "tensorflow";
    repo = "tensorflow";
    rev = "v${version}";
    hash = "sha256-61Ceoed8D65IvipM0OsXJ3xGWi5jtUDPUxhYNOffImU=";
  };

  bazel = buildPackages.bazel_6;

  nativeBuildInputs = [
    pythonEnv
    buildPackages.perl
    buildPackages.auto-patchelf
  ];

  bazelTargets = [
    "//tensorflow/lite:libtensorflowlite.so"
    "//tensorflow/lite/c:libtensorflowlite_c.so"
    "//tensorflow/lite/tools/benchmark:benchmark_model"
    "//tensorflow/lite/tools/benchmark:benchmark_model_performance_options"
  ];

  bazelFlags =
    [
      "--config=opt"
      "--cxxopt=-x"
      "--cxxopt=c++"
      "--host_cxxopt=-x"
      "--host_cxxopt=c++"

      # workaround for https://github.com/bazelbuild/bazel/issues/15359
      "--spawn_strategy=sandboxed"
      "--sandbox_debug"
    ]
    ++ lib.optionals (hostPlatform.system != buildPlatform.system) [
      "--config=${bazelHostConfigName.${hostPlatform.system}}"
    ];

  bazelBuildFlags = [
    "--cxxopt=--std=c++17"
    "--extra_toolchains=@bazel_tools//tools/python:autodetecting_toolchain_nonstrict"
  ];

  buildAttrs = {
    installPhase = ''
      mkdir -p $out/{bin,lib}

      # copy the libs and binaries into the output dir
      cp ./bazel-bin/tensorflow/lite/c/libtensorflowlite_c.so $out/lib
      cp ./bazel-bin/tensorflow/lite/libtensorflowlite.so $out/lib
      cp ./bazel-bin/tensorflow/lite/tools/benchmark/benchmark_model $out/bin
      cp ./bazel-bin/tensorflow/lite/tools/benchmark/benchmark_model_performance_options $out/bin

      find . -type f -name '*.h' | while read f; do
        path="$out/include/''${f/.\//}"
        install -D "$f" "$path"

        # remove executable bit from headers
        chmod -x "$path"
      done
    '';
    preBuild = lib.optionalString (hostPlatform.system != buildPlatform.system) ''
      # delete gdb so we do not have to patch it
      rm /build/output/external/aarch64_linux_toolchain/bin/aarch64-none-linux-gnu-gdb
      NIX_BINTOOLS=${buildPackages.stdenv.cc.bintools} auto-patchelf --libs ${buildPackages.stdenv.cc.cc.lib.lib}/lib --paths /build/output/external/aarch64_linux_toolchain
    '';

  };

  fetchAttrs.sha256 = bazelDepsSha256;

  HERMETIC_PYTHON_VERSION = "3.12";
  PYTHON_BIN_PATH = "${pythonEnv}/bin/python3.12";
  PYTHON_LIB_PATH = "${pythonEnv}/lib/python3.12/site-packages";
  CLANG_COMPILER_PATH = "${buildPackages.clang}/bin/${stdenv.cc.targetPrefix}clang";
  dontAddBazelOpts = true;
  removeRulesCC = false;

  postPatch = ''
    rm .bazelversion

    # Fix gcc-13 build failure by including missing include headers
    sed -e '1i #include <cstdint>' -i \
      tensorflow/lite/kernels/internal/spectrogram.cc
  '';

  preConfigure = ''
    patchShebangs configure
  '';

  # configure script freaks out when parameters are passed
  dontAddPrefix = true;
  configurePlatforms = [ ];

  meta = with lib; {
    description = "Open source deep learning framework for on-device inference";
    homepage = "https://www.tensorflow.org/lite";
    license = licenses.asl20;
    maintainers = with maintainers; [
      mschwaig
      cpcloud
    ];
    platforms = [
      "x86_64-linux"
      "aarch64-linux"
    ];
  };
}
