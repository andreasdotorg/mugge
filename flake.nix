{
  description = "Pi 4B audio workstation — development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachSystem [
      "x86_64-darwin"   # macOS Intel dev
      "aarch64-darwin"  # macOS Apple Silicon dev
      "aarch64-linux"   # Pi 4B deployment target
    ] (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python313;
      in
      {
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
            ]))
          ];

          buildInputs = [
            pkgs.libsndfile
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            pkgs.alsa-lib
            pkgs.libjack2
          ];

          shellHook = ''
            echo "Pi 4B audio workstation dev shell"
            echo "Python: $(python3 --version)"
            echo ""
            echo "Packages from nixpkgs: mido, python-rtmidi, fastapi,"
            echo "  uvicorn, scipy, numpy, soundfile, websockets"
            echo ""

            # pycamilladsp is not in nixpkgs — install via pip in a venv.
            if [ ! -d .venv ]; then
              echo "Creating venv for pip-only packages..."
              python3 -m venv .venv --system-site-packages
            fi
            source .venv/bin/activate

            if ! python3 -c "import camilladsp" 2>/dev/null; then
              echo "Installing pycamilladsp via pip..."
              pip install --quiet pycamilladsp
            fi

            echo "pycamilladsp: $(pip show pycamilladsp 2>/dev/null | grep Version || echo 'not installed')"
          '';
        };
      }
    );
}
