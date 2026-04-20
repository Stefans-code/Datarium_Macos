#!/bin/bash
# =============================================================
#  Datarium - Setup automatico per macOS (Intel + Apple Silicon)
#  Esegui con: bash setup_mac.sh
# =============================================================

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     DATARIUM - Setup macOS               ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Determina architettura
ARCH=$(uname -m)
echo "• Architettura: $ARCH"
echo "• macOS: $(sw_vers -productVersion)"
echo ""

# Controlla Homebrew
if ! command -v brew &> /dev/null; then
    echo "[1/4] Installazione Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    echo "[1/4] Homebrew già installato ✓"
fi

# Dipendenze di sistema necessarie per llama-cpp-python
echo "[2/4] Installazione dipendenze di sistema (cmake, xz)..."
brew install cmake xz 2>/dev/null && echo "    ✓ Dipendenze installate" || echo "    ✓ Già presenti"

# Crea e attiva venv
echo "[3/4] Creazione ambiente virtuale Python..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "    ✓ venv creato"
else
    echo "    ✓ venv già esistente"
fi

source venv/bin/activate
pip install --upgrade pip --quiet

# Installa requirements standard
echo "[4/4] Installazione dipendenze Python..."
if [ -f "requirements.txt" ]; then
    # Installa prima tutto TRANNE llama-cpp-python
    grep -v "llama.cpp\|llama_cpp\|llama-cpp" requirements.txt > /tmp/requirements_no_llama.txt
    pip install -r /tmp/requirements_no_llama.txt --quiet
fi

# Installa llama-cpp-python con flag CORRETTI per macOS
echo ""
echo "• Installazione llama-cpp-python ottimizzata per $ARCH..."
if [ "$ARCH" = "arm64" ]; then
    # Apple Silicon M1/M2/M3 - abilita Metal GPU acceleration
    echo "  → Apple Silicon (M-series): abilito Metal GPU..."
    CMAKE_ARGS="-DLLAMA_METAL=on -DCMAKE_OSX_ARCHITECTURES=arm64" \
    FORCE_CMAKE=1 \
    pip install llama-cpp-python --force-reinstall --no-cache-dir
else
    # Intel Mac
    echo "  → Intel Mac: installazione standard..."
    CMAKE_ARGS="-DLLAMA_BLAS=ON -DLLAMA_BLAS_VENDOR=Accelerate" \
    FORCE_CMAKE=1 \
    pip install llama-cpp-python --force-reinstall --no-cache-dir
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ llama-cpp-python installato correttamente!"
else
    echo ""
    echo "⚠️  Errore nell'installazione. Provo con la versione base..."
    pip install llama-cpp-python --force-reinstall --no-cache-dir
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅ Setup completato!                    ║"
echo "║  Avvia con: source venv/bin/activate     ║"
echo "║             python3 main.py              ║"
echo "╚══════════════════════════════════════════╝"
echo ""
