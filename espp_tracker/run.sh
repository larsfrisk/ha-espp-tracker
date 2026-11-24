#!/command/with-contenv bashio

export ESPP_DATA_DIR=/data
export ESPP_INGRESS=1
export TZ="$(bashio::supervisor.timezone)"

bashio::log.info "Startar ESPP-tracker"
exec python3 -I /app/app.py --host 0.0.0.0 --port 8099
