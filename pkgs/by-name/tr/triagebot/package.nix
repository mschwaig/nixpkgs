{
  rustPlatform,
  fetchFromGitHub,
  openssl,
  pkg-config,
  rustfmt,
}:

rustPlatform.buildRustPackage rec {
  pname = "triagebot";
  version = "unstable-${src.rev}";

  src = fetchFromGitHub {
    owner = "rust-lang";
    repo = "triagebot";
    rev = "4b0a0c5afa90af590d8473ab60cead4a8de0a7bc";
    hash = "sha256-cnlxGQvMDFBY6IFKZ/WeYtwSTNbAAtROEGJiYxbWFE8=";
  };

  cargoHash = "sha256-7bCmJaJefAVSHGo/lpNXfozoCH16Y1uC1J7NHGV2TWw=";

  nativeBuildInputs = [
    pkg-config
    rustfmt
  ];
  buildInputs = [ openssl ];

  checkFlags = [ "--skip=db::cert" ];

  postInstallCheck = ''
    $out/bin/triagebot --version
  '';
}
