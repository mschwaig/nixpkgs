{ lib
, buildNpmPackage
, nodePackages
, fetchFromGitHub
, runtimeShell
, esbuild
, buildGoModule
, python3
}:

# We just package the JS frontend part, not the Python reverse-proxy backend.
# NixOS can provide any another reverse proxy such as nginx.
let
  python_env = python3.withPackages (p: with p; [
    fastapi
    uvicorn
    pydantic
    python-multipart
    flask
    flask-cors
    python-socketio
    python-jose
    passlib
    uuid
    requests
    aiohttp
    peewee
    bcrypt
    langchain
    langchain-community
    chromadb
    sentence-transformers
    pypdf
    docx2txt
    unstructured
    markdown
    pypandoc
    pandas
    openpyxl
    pyxlsb
    xlrd
    faster-whisper
    pyjwt
    black
  ]
);
in
buildNpmPackage rec {
  pname = "open-webui";
  # open-webui doesn't tag versions yet.
  version = "0.0.0-unstable-2024-02-21";

  src = fetchFromGitHub {
    owner = "open-webui";
    repo = "open-webui";
    rev = "a70192ad1b2a5a13a3786a48287b29ef7febad3e";
    hash = "sha256-4DXHNoXqEPEnVCpZ+PXfAYVYmVVbqHUa94qMdFaxgG8=";
  };
  # dependencies are downloaded into a separate node_modules Nix package
  npmDepsHash = "sha256-TavFWEROSXS3GKbMzKhblLYLuN1tpXzlJG0Tm5p6fMI=";

  # We have to bake in the default URL it will use for ollama webserver here,
  # but it can be overriden in the UI later.
  PUBLIC_API_BASE_URL = "http://localhost:11434/api";

  # The path '/ollama/api' will be redirected to the specified backend URL
  OLLAMA_API_BASE_URL = PUBLIC_API_BASE_URL;

  ESBUILD_BINARY_PATH = "${lib.getExe (esbuild.override {
    buildGoModule = args: buildGoModule (args // rec {
      version = "0.18.20";
      src = fetchFromGitHub {
        owner = "evanw";
        repo = "esbuild";
        rev = "v${version}";
        hash = "sha256-mED3h+mY+4H465m02ewFK/BgA1i/PQ+ksUNxBlgpUoI=";
      };
      vendorHash = "sha256-+BfxCyg0KkDQpHt/wycy/8CTG6YBA/VJvJFhhzUnSiQ=";
    });
  })}";
  # "npm run build" creates a static page in the "build" folder.
  installPhase = ''
    mkdir -p $out/lib/static
    cp -R ./build/. $out/lib/static
    cp -R ./backend $out/lib/

    mkdir -p $out/bin
    cat <<EOF >>$out/bin/${pname}
    #!${runtimeShell}
    ${python_env}/bin/uvicorn main:app --app-dir $out/lib/backend
    EOF
    chmod +x $out/bin/${pname}
  '';

  # --host 0.0.0.0 --port "$PORT" --forwarded-allow-ips '*'
  meta = with lib; {
    description = "ChatGPT-Style Web Interface for Ollama";
    longDescription = ''
      Tools like Ollama make open-source large langue models (LLM) accessible and almost
      trivial to download and run them locally on a consumer computer.
      However, Ollama only runs in a terminal and doesn't store any chat history.
      Open-WebUI is a web frontend on top of Ollama that looks and behaves similar to ChatGPT's web frontend.
      You can have separate chats with different LLMs that are saved in your browser,
      automatic Markdown and Latex rendering, upload files etc.
      This package contains two parts:
      - `<nix-store-package-path>/lib` The WebUI as a compiled, static html folder to bundle in your web server
      - `<nix-store-package-path>/bin/${pname}` A runnable webserver the serves the WebUI for convenience.
    '';
    homepage = "https://github.com/open-webui/open-webui";
    license = licenses.mit;
    mainProgram = pname;
    maintainers = with maintainers; [ malteneuss ];
    platforms = platforms.all;
  };
}
