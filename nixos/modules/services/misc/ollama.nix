{ config, pkgs, lib, ... }:

with lib;

let cfg = config.services.ollama;

in {
  options = {
    services.ollama = {
      enable = lib.mkEnableOption (
        lib.mdDoc ''
        Ollama backend service.
        Run state-of-the-art AI large language models (LLM) similar to ChatGPT locally with privacy
        on your personal computer.

        This module provides the `ollama serve` backend runner service so that you can run
        `ollam run <model-name>` locally in a terminal; this will automatically download the
        LLM model and open a chat. See <https://github.com/jmorganca/ollama#quickstart>.
        The model names can be looked up on <https://ollama.ai/library> and are available in
        varying sizes to fit your CPU, GPU, RAM and disk storage.
        See <https://github.com/jmorganca/ollama#model-library>.

        Optional: This module is intended to be run locally, but can be served from a (home) server,
        ideally behind a secured reverse-proxy.
        Look at <https://nixos.wiki/wiki/Nginx> or <https://nixos.wiki/wiki/Caddy>
        on how to set up a reverse proxy.

        Optional: This service doesn't persist any chats and is only available in the terminal.
        For a convenient, graphical web app on top of it, take look at
        <https://github.com/open-webui/open-webui>, also as `open-webui` in Nixpkgs.
        ''
      );

      listenAddress = lib.mkOption {
        type = lib.types.str;
        default = "127.0.0.1:11434";
        description = lib.mdDoc ''
          Specifies the bind address on which the ollama server HTTP interface listens.
        '';
      };
      package = lib.mkPackageOption pkgs "ollama" { };

      cors_origins = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "https://myserver:8080,http://10.0.0.10:*";
        description = lib.mdDoc ''
          Allow access from web apps that are served under some (different) URL.
          If a web app like Open-WebUI is available/served on `https://myserver:8080`,
          then add this URL here. Otherwise the Ollama backend server will reject the
          UIs request and return 403 forbidden due to CORS.
          See <https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS>.
        '';
      };
    };
  };

  config = mkIf cfg.enable {
    systemd = {
      services.ollama = {
        wantedBy = [ "multi-user.target" ];
        description = "Ollama: A backend service for local large language models (LLMs).";
        after = [ "network.target" ];
        environment = {
          HOME = "%S/ollama";
          OLLAMA_MODELS = "%S/ollama/models";
          OLLAMA_HOST = cfg.listenAddress;
          OLLAMA_ORIGINS = cfg.cors_origins;
        };
        serviceConfig = {
          ExecStart = "${lib.getExe cfg.package} serve";
          WorkingDirectory = "/var/lib/ollama";
          StateDirectory = [ "ollama" ];
          DynamicUser = true;
          Restart = "on-failure";
          RestartSec = 3;
        };
      };
    };
  };
  meta.maintainers = with lib.maintainers; [ onny malteneuss ];
}
