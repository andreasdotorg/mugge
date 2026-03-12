{
  description = "Pi 4B audio workstation — development environment and NixOS deployment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils/11707dc2f618dd54ca8739b309ec4fc024de578b";
    nixos-hardware.url = "github:NixOS/nixos-hardware";
  };

  outputs = { self, nixpkgs, flake-utils, nixos-hardware }:
    (flake-utils.lib.eachSystem [
      "x86_64-darwin"   # macOS Intel dev
      "aarch64-darwin"  # macOS Apple Silicon dev
      "aarch64-linux"   # Pi 4B deployment target
    ] (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python313;
        pycamilladsp = python.pkgs.buildPythonPackage rec {
          pname = "camilladsp";
          version = "3.0.0";
          pyproject = true;
          src = pkgs.fetchFromGitHub {
            owner = "HEnquist";
            repo = "pycamilladsp";
            rev = "v${version}";
            hash = "sha256-WyyeYAEi2s46WSSuSl/s04+yW4rXWMPUx+oT1bVP3HM=";
          };
          build-system = with python.pkgs; [ setuptools ];
          dependencies = with python.pkgs; [
            pyyaml
            websocket-client
          ];
          doCheck = false;  # tests need a running CamillaDSP instance
        };
      in
      {
        packages = { } // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          mixxx = pkgs.mixxx;
        };

        devShells.default = pkgs.mkShell {
          packages = [
            (python.withPackages (ps: [
              ps.mido
              ps.python-rtmidi
              ps.fastapi
              ps.uvicorn
              ps.scipy
              ps.numpy
              ps.soundfile
              ps.websockets
              ps.pyyaml
              # Testing
              ps.pytest
              ps.httpx
              ps.playwright
              ps.pytest-playwright
              pycamilladsp
            ]))
            pkgs.playwright-driver
          ];

          buildInputs = [
            pkgs.libsndfile
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            pkgs.alsa-lib
            pkgs.libjack2
          ];

          shellHook = ''
            export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
            export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

            echo "Pi 4B audio workstation dev shell"
            echo "Python: $(python3 --version)"
            echo ""
            echo "Packages from nixpkgs: mido, python-rtmidi, fastapi,"
            echo "  uvicorn, scipy, numpy, soundfile, websockets,"
            echo "  pytest, playwright, pytest-playwright"
            echo ""

            echo "pycamilladsp: $(python3 -c 'from camilladsp.versions import VERSION; print(VERSION)' 2>/dev/null || echo 'not available')"
          '';
        };
      }
    ))
    // {
      nixosConfigurations.mugge = nixpkgs.lib.nixosSystem {
        system = "aarch64-linux";
        modules = [
          nixos-hardware.nixosModules.raspberry-pi-4
          ./nix/nixos/configuration.nix
        ];
      };
    };
}
