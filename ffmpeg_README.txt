FFmpeg incluso in Datarium
==========================

Datarium include una copia NON MODIFICATA di FFmpeg 9.0, usata come programma separato
(viene avviato da riga di comando) per generare i proxy video e leggere durata,
risoluzione, codec e timecode dei filmati.

FFmpeg e' software libero di terze parti, distribuito con licenza GNU GPL
(testo completo nel file LICENSE.txt in questa cartella). FFmpeg non fa parte di
Datarium e non e' coperto dalla licenza di Datarium.

Provenienza dei binari inclusi:
  - Windows (x64):       build "gpl-shared" n9.0 di BtbN
                         https://github.com/BtbN/FFmpeg-Builds
  - macOS (Apple Silicon e Intel) e Linux (x64): build statiche release 9.0.2 di Martin Riedl
                         https://ffmpeg.martin-riedl.de

Codice sorgente:
  - FFmpeg:              https://ffmpeg.org/download.html  (git: https://git.ffmpeg.org/ffmpeg.git)
  - script di build:     https://github.com/BtbN/FFmpeg-Builds
                         https://git.martin-riedl.de/ffmpeg/build-script

Su richiesta forniamo una copia del codice sorgente corrispondente: scrivere al
supporto Nexflamma indicando la versione di Datarium.
