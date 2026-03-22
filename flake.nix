{
  description = "Pi 4B audio workstation — development environment and NixOS deployment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    flake-utils.url = "github:numtide/flake-utils/11707dc2f618dd54ca8739b309ec4fc024de578b";
    nixos-hardware.url = "github:NixOS/nixos-hardware";
    nixgl = {
      url = "github:nix-community/nixGL";
      inputs.nixpkgs.follows = "nixpkgs";       # prevent GLIBC version mismatch
      inputs.flake-utils.follows = "flake-utils"; # deduplicate
    };
  };

  outputs = { self, nixpkgs, flake-utils, nixos-hardware, nixgl }:
    (flake-utils.lib.eachSystem [
      "x86_64-darwin"   # macOS Intel dev
      "aarch64-darwin"  # macOS Apple Silicon dev
      "aarch64-linux"   # Pi 4B deployment target
    ] (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = nixpkgs.lib.optionals (system == "aarch64-linux") [
            nixgl.overlay
          ];
        };
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

        # Python with test dependencies — shared by checks and unit-test apps.
        testPython = python.withPackages (ps: [
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
          pycamilladsp
        ]);

        # Python with e2e dependencies — adds playwright on top of testPython's deps.
        # Used by test-e2e app and devShell.
        e2ePython = python.withPackages (ps: [
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
          pycamilladsp
          # E2E / browser testing
          ps.playwright
          ps.pytest-playwright
        ]);

        # CamillaDSP binary for integration testing (TK-189).
        # Built with websocket + file backend — no JACK/PulseAudio needed.
        # The File capture/playback type is always compiled in (not a feature).
        # Used by room-correction integration tests to replace MockCamillaClient.
        camilladsp-test = pkgs.rustPlatform.buildRustPackage {
          pname = "camilladsp";
          version = "3.0.1";
          src = pkgs.fetchFromGitHub {
            owner = "HEnquist";
            repo = "camilladsp";
            rev = "v3.0.1";
            hash = "sha256-IJ1sYprBh8ys1Og3T3newIDlBlR0PoQiblbJmzLbsfs=";
          };
          cargoLock.lockFile = ./src/camilladsp-test/Cargo.lock;
          # Upstream doesn't ship a Cargo.lock — copy ours into the source.
          postPatch = ''
            cp ${./src/camilladsp-test/Cargo.lock} Cargo.lock
          '';
          # Default features = ["websocket"] — includes tungstenite WS server.
          # No extra features needed: File I/O backend is always compiled in.
          buildNoDefaultFeatures = false;
          nativeBuildInputs = [ pkgs.pkg-config ];
          buildInputs =
            pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [ pkgs.alsa-lib ]
            ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isDarwin [
              pkgs.apple-sdk  # Provides AudioUnit, CoreAudio, CoreServices frameworks
            ];
          doCheck = false;  # CamillaDSP tests require audio hardware
        };

        # nixGL wrapper for Mixxx on non-NixOS (Debian Trixie).
        # nixGLIntel is the Mesa wrapper — works for all Mesa drivers
        # including V3D on the Pi 4. Despite the "Intel" name, it sets
        # LIBGL_DRIVERS_PATH, GBM_BACKENDS_PATH, and LD_LIBRARY_PATH
        # to point at Nix's Mesa, which contains the V3D DRI driver.
        #
        # We also prepend host PipeWire/JACK library paths so that
        # pw-jack compatibility works (Mixxx uses JACK via PipeWire).
        # On non-NixOS, PipeWire's pw-jack libraries live under the
        # host's /usr/lib, which Nix isolates away.

        mixxx-wrapped = let
          nixGLMesa = pkgs.nixgl.nixGLIntel;
        in pkgs.writeShellApplication {
          name = "mixxx";
          runtimeInputs = [ nixGLMesa pkgs.mixxx ];
          text = ''
            # Host PipeWire/JACK paths for non-NixOS Debian Trixie.
            # pw-jack provides libjack.so that routes JACK calls through
            # PipeWire. Mixxx links against JACK, so it needs to find
            # the host's pw-jack library.
            HOST_LIB="/usr/lib/aarch64-linux-gnu"
            if [ -d "$HOST_LIB/pipewire-0.3/jack" ]; then
              export LD_LIBRARY_PATH="$HOST_LIB/pipewire-0.3/jack''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            fi

            exec nixGLIntel mixxx "$@"
          '';
        };

        # Workspace source for pcm-bridge + signal-gen + audio-common.
        # Cleaned to include only the workspace root and member crates.
        rustWorkspaceSrc = pkgs.lib.cleanSourceWith {
          src = ./src;
          filter = path: type:
            let baseName = builtins.baseNameOf path; in
            # Include workspace root files
            baseName == "Cargo.toml" || baseName == "Cargo.lock"
            # Include workspace member directories
            || pkgs.lib.hasPrefix (toString ./src/audio-common) (toString path)
            || pkgs.lib.hasPrefix (toString ./src/pcm-bridge) (toString path)
            || pkgs.lib.hasPrefix (toString ./src/signal-gen) (toString path);
        };

        # Shared PipeWire build args for Rust crates.
        rustPwBuildArgs = {
          nativeBuildInputs = [ pkgs.pkg-config pkgs.llvmPackages.libclang ];
          buildInputs = [ pkgs.pipewire ];
          LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
          BINDGEN_EXTRA_CLANG_ARGS = builtins.toString [
            "-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include"
            "-isystem ${pkgs.glibc.dev}/include"
          ];
        };

        # Rust PipeWire tools (Linux-only, need libpipewire).
        # Built from the Cargo workspace (audio-common + pcm-bridge + signal-gen).
        pcm-bridge = pkgs.rustPlatform.buildRustPackage (rustPwBuildArgs // {
          pname = "pcm-bridge";
          version = "0.1.0";
          src = rustWorkspaceSrc;
          cargoLock.lockFile = ./src/Cargo.lock;
          buildAndTestSubdir = "pcm-bridge";
        });

        signal-gen = pkgs.rustPlatform.buildRustPackage (rustPwBuildArgs // {
          pname = "pi4audio-signal-gen";
          version = "0.1.0";
          src = rustWorkspaceSrc;
          cargoLock.lockFile = ./src/Cargo.lock;
          buildAndTestSubdir = "signal-gen";
        });

        graph-manager = pkgs.rustPlatform.buildRustPackage {
          pname = "pi4audio-graph-manager";
          version = "0.1.0";
          src = ./src/graph-manager;
          cargoLock.lockFile = ./src/graph-manager/Cargo.lock;
          nativeBuildInputs = [ pkgs.pkg-config pkgs.llvmPackages.libclang ];
          buildInputs = [ pkgs.pipewire ];
          LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
          BINDGEN_EXTRA_CLANG_ARGS = builtins.toString [
            "-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include"
            "-isystem ${pkgs.glibc.dev}/include"
          ];
        };
      in
      {
        packages = {
          # CamillaDSP with file backend for integration testing (all platforms).
          inherit camilladsp-test;
        } // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # Unwrapped Mixxx (for NixOS or debugging)
          mixxx = pkgs.mixxx;

          # Wrapped Mixxx with nixGL + host PipeWire/JACK (for non-NixOS)
          mixxx-gl = mixxx-wrapped;

          # Passive PipeWire monitor-port PCM bridge for web UI.
          inherit pcm-bridge;

          # RT signal generator for measurement and test tooling (D-037).
          inherit signal-gen;

          # PipeWire graph manager — session manager for link topology (GM-7).
          inherit graph-manager;

          # Default package for `nix run .#` on Linux
          default = mixxx-wrapped;
        };

        devShells.default = pkgs.mkShell {
          packages = [
            e2ePython
            pkgs.playwright-driver
            camilladsp-test  # Real CamillaDSP for integration tests (TK-189)
            # Rust toolchain — same version as buildRustPackage uses.
            pkgs.cargo
            pkgs.rustc
            pkgs.clippy
            pkgs.rust-analyzer
          ];

          buildInputs = [
            pkgs.libsndfile
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            pkgs.alsa-lib
            pkgs.libjack2
            # PipeWire dev deps for cargo build of PW crates
            pkgs.pipewire
            pkgs.pkg-config
            pkgs.llvmPackages.libclang
          ];

          shellHook = ''
            export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
            export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
          '' + pkgs.lib.optionalString pkgs.stdenv.hostPlatform.isLinux ''
            export LIBCLANG_PATH="${pkgs.llvmPackages.libclang.lib}/lib"
            export BINDGEN_EXTRA_CLANG_ARGS="-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include -isystem ${pkgs.glibc.dev}/include"
          '' + ''

            echo "Pi 4B audio workstation dev shell"
            echo "Python: $(python3 --version)"
            echo "Rust:   $(rustc --version 2>/dev/null || echo 'not available')"
            echo "Cargo:  $(cargo --version 2>/dev/null || echo 'not available')"
            echo ""
            echo "Packages from nixpkgs: mido, python-rtmidi, fastapi,"
            echo "  uvicorn, scipy, numpy, soundfile, websockets,"
            echo "  pytest, playwright, pytest-playwright"
            echo ""

            echo "pycamilladsp: $(python3 -c 'from camilladsp.versions import VERSION; print(VERSION)' 2>/dev/null || echo 'not available')"
          '';
        };

        # -----------------------------------------------------------------
        # Checks — sandboxed test derivations for `nix flake check`
        # -----------------------------------------------------------------
        checks = {
          test-web-ui = pkgs.runCommand "test-web-ui" {
            nativeBuildInputs = [ testPython ];
            PI_AUDIO_MOCK = "1";
          } ''
            cp -r ${./src/web-ui} web-ui
            cp -r ${./src/room-correction} room-correction
            chmod -R u+w web-ui room-correction
            cd web-ui
            python -m pytest tests/ -v --ignore=tests/e2e/ --tb=short
            touch $out
          '';

          test-room-correction = pkgs.runCommand "test-room-correction" {
            nativeBuildInputs = [ testPython camilladsp-test ];
            PI_AUDIO_MOCK = "1";
          } ''
            cp -r ${./src/room-correction} room-correction
            cp ${./src/camilladsp-test/test_config.yml} room-correction/test_camilladsp.yml
            chmod -R u+w room-correction
            cd room-correction
            python -m pytest tests/ -v --tb=short
            touch $out
          '';

          test-midi = pkgs.runCommand "test-midi" {
            nativeBuildInputs = [ testPython ];
            PI_AUDIO_MOCK = "1";
          } ''
            cp -r ${./src/midi} midi
            cp -r ${./configs} configs
            chmod -R u+w midi configs
            cd midi
            python -m pytest tests/ -v --tb=short
            touch $out
          '';

          test-drivers = pkgs.runCommand "test-drivers" {
            nativeBuildInputs = [ testPython ];
            PI_AUDIO_MOCK = "1";
          } ''
            cp -r ${./scripts/drivers} drivers
            mkdir -p scripts
            ln -s "$PWD/drivers" scripts/drivers
            chmod -R u+w drivers
            cd drivers
            python -m pytest tests/ -v --tb=short
            touch $out
          '';
          # Graph-manager pure-logic tests (no PipeWire needed — runs on all platforms).
          test-graph-manager = pkgs.runCommand "test-graph-manager" {
            nativeBuildInputs = [ pkgs.cargo pkgs.rustc ];
          } ''
            cp -r ${./src/graph-manager} graph-manager
            chmod -R u+w graph-manager
            cd graph-manager
            HOME=$TMPDIR cargo test --no-default-features --release 2>&1
            touch $out
          '';
        } // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # Rust PipeWire tools — cargo test runs during buildRustPackage.
          test-pcm-bridge = pcm-bridge;
          test-signal-gen = signal-gen;

          # Full graph-manager build + test (Linux with PipeWire).
          test-graph-manager-full = pkgs.rustPlatform.buildRustPackage {
            pname = "pi4audio-graph-manager";
            version = "0.1.0";
            src = ./src/graph-manager;
            cargoLock.lockFile = ./src/graph-manager/Cargo.lock;
            nativeBuildInputs = [ pkgs.pkg-config pkgs.llvmPackages.libclang ];
            buildInputs = [ pkgs.pipewire ];
            LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
            BINDGEN_EXTRA_CLANG_ARGS = builtins.toString [
              "-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include"
              "-isystem ${pkgs.glibc.dev}/include"
            ];
          };
        };

        # -----------------------------------------------------------------
        # Apps — runnable test / dev commands via `nix run .#<name>`
        # -----------------------------------------------------------------
        apps = {
          test-unit = {
            type = "app";
            program = "${pkgs.writeShellScript "test-unit" ''
              export PI_AUDIO_MOCK=1
              cd ${toString ./.}/src/web-ui
              exec ${testPython}/bin/python -m pytest tests/ -v --ignore=tests/e2e/ "$@"
            ''}";
          };

          test-e2e = {
            type = "app";
            program = "${pkgs.writeShellScript "test-e2e" ''
              export PI_AUDIO_MOCK=1
              export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
              export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
              cd ${toString ./.}/src/web-ui
              exec ${e2ePython}/bin/python -m pytest tests/e2e/ -v "$@"
            ''}";
          };

          test-room-correction = {
            type = "app";
            program = "${pkgs.writeShellScript "test-room-correction" ''
              export PI_AUDIO_MOCK=1
              cd ${toString ./.}/src/room-correction
              exec ${testPython}/bin/python -m pytest tests/ -v "$@"
            ''}";
          };

          test-all = {
            type = "app";
            program = "${pkgs.writeShellScript "test-all" ''
              export PI_AUDIO_MOCK=1
              set -e
              echo "=== web-ui unit tests ==="
              cd ${toString ./.}/src/web-ui
              ${testPython}/bin/python -m pytest tests/ -v --ignore=tests/e2e/ --tb=short
              echo ""
              echo "=== room-correction tests ==="
              cd ${toString ./.}/src/room-correction
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== midi tests ==="
              cd ${toString ./.}/src/midi
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== drivers tests ==="
              cd ${toString ./.}/scripts/drivers
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== graph-manager tests ==="
              cd ${toString ./.}/src/graph-manager
              HOME="''${HOME:-/tmp}" CARGO_TARGET_DIR="''${HOME:-/tmp}/.cargo-target/pi4audio-gm" PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH" cargo test --no-default-features --release 2>&1
              echo ""
              echo "All test suites passed."
              echo "(pcm-bridge and signal-gen: run nix run .#test-pcm-bridge / .#test-signal-gen on Linux)"
            ''}";
          };

          test-audio-common = {
            type = "app";
            program = "${pkgs.writeShellScript "test-audio-common" ''
              export HOME="''${HOME:-/tmp}"
              export CARGO_TARGET_DIR="''${HOME}/.cargo-target/pi4audio-ws"
              export PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH"
              cd ${toString ./.}/src
              exec cargo test --locked -p audio-common "$@"
            ''}";
          };

          test-graph-manager = {
            type = "app";
            program = "${pkgs.writeShellScript "test-graph-manager" ''
              export HOME="''${HOME:-/tmp}"
              export CARGO_TARGET_DIR="''${HOME}/.cargo-target/pi4audio-gm"
              export PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH"
              cd ${toString ./.}/src/graph-manager
              exec cargo test --no-default-features "$@"
            ''}";
          };

          test-everything = {
            type = "app";
            program = "${pkgs.writeShellScript "test-everything" ''
              set -e
              echo "========== test-all (unit + integration) =========="
              export PI_AUDIO_MOCK=1
              cd ${toString ./.}/src/web-ui
              ${testPython}/bin/python -m pytest tests/ -v --ignore=tests/e2e/ --tb=short
              echo ""
              echo "=== room-correction tests ==="
              cd ${toString ./.}/src/room-correction
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== midi tests ==="
              cd ${toString ./.}/src/midi
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== drivers tests ==="
              cd ${toString ./.}/scripts/drivers
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== graph-manager tests ==="
              cd ${toString ./.}/src/graph-manager
              HOME="''${HOME:-/tmp}" CARGO_TARGET_DIR="''${HOME:-/tmp}/.cargo-target/pi4audio-gm" PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH" cargo test --no-default-features --release 2>&1
              echo ""
              echo "========== test-e2e (browser tests) =========="
              export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
              export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
              cd ${toString ./.}/src/web-ui
              ${e2ePython}/bin/python -m pytest tests/e2e/ -v --tb=short
              echo ""
              echo "All test suites passed (unit + integration + e2e)."
            ''}";
          };

          serve = {
            type = "app";
            program = "${pkgs.writeShellScript "serve" ''
              export PI_AUDIO_MOCK=1
              cd ${toString ./.}/src/web-ui
              exec ${testPython}/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
            ''}";
          };
        } // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # PipeWire Rust tools — require libpipewire (Linux only).
          test-pcm-bridge = {
            type = "app";
            program = "${pkgs.writeShellScript "test-pcm-bridge" ''
              export HOME="''${HOME:-/tmp}"
              export CARGO_TARGET_DIR="''${HOME}/.cargo-target/pi4audio-ws"
              export PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.pkg-config}/bin:${pkgs.stdenv.cc}/bin:$PATH"
              export PKG_CONFIG_PATH="${pkgs.pipewire.dev}/lib/pkgconfig''${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
              export LIBCLANG_PATH="${pkgs.llvmPackages.libclang.lib}/lib"
              export BINDGEN_EXTRA_CLANG_ARGS="-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include -isystem ${pkgs.glibc.dev}/include"
              cd ${toString ./.}/src
              exec cargo test --locked -p pcm-bridge "$@"
            ''}";
          };

          test-signal-gen = {
            type = "app";
            program = "${pkgs.writeShellScript "test-signal-gen" ''
              export HOME="''${HOME:-/tmp}"
              export CARGO_TARGET_DIR="''${HOME}/.cargo-target/pi4audio-ws"
              export PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.pkg-config}/bin:${pkgs.stdenv.cc}/bin:$PATH"
              export PKG_CONFIG_PATH="${pkgs.pipewire.dev}/lib/pkgconfig''${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
              export LIBCLANG_PATH="${pkgs.llvmPackages.libclang.lib}/lib"
              export BINDGEN_EXTRA_CLANG_ARGS="-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include -isystem ${pkgs.glibc.dev}/include"
              cd ${toString ./.}/src
              exec cargo test --locked -p pi4audio-signal-gen "$@"
            ''}";
          };
        };
      }
    ))
    // {
      nixosConfigurations.mugge =
        let
          system = "aarch64-linux";
          pkgs = import nixpkgs {
            inherit system;
            overlays = [ nixgl.overlay ];
          };
          # Build our custom Rust packages for the Pi target.
          # These are passed to NixOS modules via specialArgs so service
          # units can reference Nix store paths instead of ~/bin.
          rustPwArgs = {
            nativeBuildInputs = [ pkgs.pkg-config pkgs.llvmPackages.libclang ];
            buildInputs = [ pkgs.pipewire ];
            LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
            BINDGEN_EXTRA_CLANG_ARGS = builtins.toString [
              "-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include"
              "-isystem ${pkgs.glibc.dev}/include"
            ];
          };

          # Workspace source for pcm-bridge + signal-gen + audio-common.
          workspaceSrc = pkgs.lib.cleanSourceWith {
            src = ./src;
            filter = path: type:
              let baseName = builtins.baseNameOf path; in
              baseName == "Cargo.toml" || baseName == "Cargo.lock"
              || pkgs.lib.hasPrefix (toString ./src/audio-common) (toString path)
              || pkgs.lib.hasPrefix (toString ./src/pcm-bridge) (toString path)
              || pkgs.lib.hasPrefix (toString ./src/signal-gen) (toString path);
          };
        in
        nixpkgs.lib.nixosSystem {
          inherit system;
          specialArgs = {
            pi4audio-packages = {
              graph-manager = pkgs.rustPlatform.buildRustPackage (rustPwArgs // {
                pname = "pi4audio-graph-manager";
                version = "0.1.0";
                src = ./src/graph-manager;
                cargoLock.lockFile = ./src/graph-manager/Cargo.lock;
              });
              pcm-bridge = pkgs.rustPlatform.buildRustPackage (rustPwArgs // {
                pname = "pcm-bridge";
                version = "0.1.0";
                src = workspaceSrc;
                cargoLock.lockFile = ./src/Cargo.lock;
                buildAndTestSubdir = "pcm-bridge";
              });
              signal-gen = pkgs.rustPlatform.buildRustPackage (rustPwArgs // {
                pname = "pi4audio-signal-gen";
                version = "0.1.0";
                src = workspaceSrc;
                cargoLock.lockFile = ./src/Cargo.lock;
                buildAndTestSubdir = "signal-gen";
              });
            };
          };
          modules = [
            nixos-hardware.nixosModules.raspberry-pi-4
            ./nix/nixos/configuration.nix
          ];
        };
    };
}
