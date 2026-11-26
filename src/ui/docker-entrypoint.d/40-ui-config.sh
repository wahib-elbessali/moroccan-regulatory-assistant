#!/bin/sh
set -eu

read_setting() {
  awk -v section="$1" -v key="$2" '
    $0 ~ ("^" section ":[[:space:]]*$") { in_section = 1; next }
    /^[^[:space:]#][^:]*:/ { in_section = 0 }
    in_section && $1 == key ":" { gsub(/#.*/, "", $2); print $2; exit }
  ' /app/config.yaml
}

min_password_length="$(read_setting auth min_password_length)"
max_question_chars="$(read_setting agents max_question_chars)"
case "$min_password_length" in ''|*[!0-9]*) echo "Invalid auth.min_password_length in /app/config.yaml" >&2; exit 1 ;; esac
case "$max_question_chars" in ''|*[!0-9]*) echo "Invalid agents.max_question_chars in /app/config.yaml" >&2; exit 1 ;; esac
if [ "$min_password_length" -lt 1 ] || [ "$max_question_chars" -lt 1 ]; then
  echo "UI limits in /app/config.yaml must be positive integers" >&2
  exit 1
fi

printf 'window.__APP_CONFIG__ = Object.freeze({ minPasswordLength: %s, maxQuestionChars: %s });\n' \
  "$min_password_length" "$max_question_chars" > /usr/share/nginx/html/runtime-config.js
