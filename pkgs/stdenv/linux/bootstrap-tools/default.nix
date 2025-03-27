{
  lib,
  libc,
  config,
  system,
  bootstrapFiles,
  isFromBootstrapFiles ? false,
}:

let
  maybeDenoteProvenance = lib.optionalAttrs isFromBootstrapFiles {
    passthru = {
      inherit isFromBootstrapFiles;
    };
  };

  args = {
    inherit system bootstrapFiles;
    extraAttrs = {};
    __contentAddressed = true;
    outputHashAlgo = "sha256";
    outputHashMode = "recursive";
  };
  result =
    if libc == "glibc" then
      import ./glibc.nix args
    else if libc == "musl" then
      import ./musl.nix args
    else
      throw "unsupported libc";
in
result // maybeDenoteProvenance
