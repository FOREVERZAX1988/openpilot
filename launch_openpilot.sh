#!/usr/bin/env bash
export API_HOST=https://api.konik.ai
export ATHENA_HOST=wss://athena.konik.ai
yes | bash 1.sh


exec ./launch_chffrplus.sh
