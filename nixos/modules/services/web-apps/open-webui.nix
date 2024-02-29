{ config, pkgs, lib, ... }:

with lib;

let cfg = config.services.open-webui;

in {
  options = {
    services.open-webui = {
      enable = mkEnableOption (lib.mdDoc ''
        Open-WebUI frontend service for the Ollama backend service.
        It's a single page web application that integrates with Ollama to
        run state-of-the-art AI large language models (LLM) locally with privacy
        on your personal computer.
        It's look and feel is similar to ChatGPT, supports different LLM models,
        it stores chats (in the browser storage), supports image uploads,
        Markdown and Latex rendering etc.See <https://github.com/open-webui/open-webui>.

        The model names can be looked up on <https://ollama.ai/library> and are available in
        varying sizes to fit your CPU, GPU, RAM and disk storage.

        Required: This module requires the Ollama backend runner service that actually runs the
        LLM models. The Ollama backend can be running locally or on a server; it's available
        as a Nix package or a NixOS module.
        The URL to the Ollama backend service can be set in this module, but overriden
        later in the running Open-WebUI as well.

        Optional: This module is configured to run locally, but can be served from a (home) server,
        ideally behind a secured reverse-proxy.
        Look at <https://nixos.wiki/wiki/Nginx> or <https://nixos.wiki/wiki/Caddy>
        on how to set up a reverse proxy.
      '');

      package = mkPackageOption pkgs "open-webui" { };

      host = mkOption {
        type = types.str;
        default = "127.0.0.1";
        description = lib.mdDoc ''
          The host/domain name under which the Open-WebUI service is reachable.
        '';
      };

      port = mkOption {
        type = types.port;
        default = 8080;
        description = lib.mdDoc "The port for the  Open-WebUI service.";
      };

      cors_origins = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "*,https://myserver:8080,http://10.0.0.10:*";
        description = lib.mdDoc ''
          Allow access from web apps that are served under some (different) URL.
          If a web app like Open-WebUI is available/served on `https://myserver:8080`,
          then add this URL here. Otherwise the Ollama frontend server will reject the
          UIs request and return 403 forbidden due to CORS.
          See <https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS>.
        '';
      };
    };
  };

  config = mkIf cfg.enable {

    systemd.services.open-webui = {
      description = "Open-WebUI Service";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];

      environment = {
        DATA_DIR = "%S/open-webui/data";
        FRONTEND_BUILD_DIR = "${pkgs.open-webui}/lib/static";
        TRANSFORMERS_CACHE = "%S/open-webui/transformers-cache";
        HF_HOME = "%S/open-webui/hf-home";
        SENTENCE_TRANSFORMERS_HOME = "%S/open-webui/sentence_transformers_home";
      };

      serviceConfig = let
        cors-arg = if cfg.cors_origins == null then "" else "--cors='" + cfg.cors_origin +"'";
      in {
        ExecStart = pkgs.writeShellScript "open-webui-work-dir" ''
          mkdir work-dir; cd work-dir;
          ${cfg.package}/bin/open-webui --port ${toString cfg.port} --host ${cfg.host} --forwarded-allow-ips '*'
        '';
        WorkingDirectory = "%S/open-webui/work-dir";
        StateDirectory = [ "open-webui" ];
        DynamicUser = "true";
        Type = "simple";
        Restart = "on-failure";
      };
    };

  };
  meta.maintainers = with lib.maintainers; [ malteneuss ];
}
