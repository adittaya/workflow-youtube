#!/usr/bin/env bash
# installer/interactive/ui.sh — Interactive terminal UI library
# Provides: colors, progress bars, spinners, menus, prompts, boxes.
# Detects TTY for safe color output (no colors in pipes).
# All functions are pure bash — no external dependencies.

# ───────────────────────────────────────────────────────────────
#  Color definitions (disabled in non-TTY)
# ───────────────────────────────────────────────────────────────

_ui_init_colors() {
  if [ -t 1 ] && [ -t 2 ] && command -v tput &>/dev/null; then
    # Terminal supports colors
    _UI_RED=$'\033[0;31m'
    _UI_GREEN=$'\033[0;32m'
    _UI_YELLOW=$'\033[0;33m'
    _UI_BLUE=$'\033[0;34m'
    _UI_MAGENTA=$'\033[0;35m'
    _UI_CYAN=$'\033[0;36m'
    _UI_BOLD=$'\033[1m'
    _UI_DIM=$'\033[2m'
    _UI_NC=$'\033[0m'
    _UI_TTY=true
  else
    _UI_RED=""
    _UI_GREEN=""
    _UI_YELLOW=""
    _UI_BLUE=""
    _UI_MAGENTA=""
    _UI_CYAN=""
    _UI_BOLD=""
    _UI_DIM=""
    _UI_NC=""
    _UI_TTY=false
  fi
}

_ui_init_colors

# ───────────────────────────────────────────────────────────────
#  Color helpers
# ───────────────────────────────────────────────────────────────

ui_color() {
  local color_name="$1"
  shift
  local text="$*"

  case "${color_name^^}" in
    RED)     echo -e "${_UI_RED}${text}${_UI_NC}" ;;
    GREEN)   echo -e "${_UI_GREEN}${text}${_UI_NC}" ;;
    YELLOW)  echo -e "${_UI_YELLOW}${text}${_UI_NC}" ;;
    BLUE)    echo -e "${_UI_BLUE}${text}${_UI_NC}" ;;
    CYAN)    echo -e "${_UI_CYAN}${text}${_UI_NC}" ;;
    MAGENTA) echo -e "${_UI_MAGENTA}${text}${_UI_NC}" ;;
    BOLD)    echo -e "${_UI_BOLD}${text}${_UI_NC}" ;;
    DIM)     echo -e "${_UI_DIM}${text}${_UI_NC}" ;;
    *)       echo -e "${text}" ;;
  esac
}

# ───────────────────────────────────────────────────────────────
#  Screen control
# ───────────────────────────────────────────────────────────────

ui_clear() {
  if [ "$_UI_TTY" = true ]; then
    tput clear 2>/dev/null || printf '\033[2J\033[H'
  fi
}

ui_separator() {
  local width="${1:-60}"
  local char="${2:-─}"
  local line=""
  for ((i = 0; i < width; i++)); do
    line+="$char"
  done
  echo -e "${_UI_DIM}${line}${_UI_NC}"
}

# ───────────────────────────────────────────────────────────────
#  Welcome banner
# ───────────────────────────────────────────────────────────────

ui_welcome() {
  local app_name="${1:-VPLink}"
  local version="${2:-3.0}"

  local banner_width=56
  local padding=$(( (banner_width - ${#app_name} - ${#version} - 3) / 2 ))
  local pad_left=""
  local pad_right=""
  for ((i = 0; i < padding; i++)); do pad_left+=" "; done
  for ((i = 0; i < padding; i++)); do pad_right+=" "; done
  # Adjust for odd difference
  local total_used=$(( ${#pad_left} + ${#app_name} + 3 + ${#version} + ${#pad_right} ))
  if [ $total_used -lt $banner_width ]; then
    pad_right+=" "
  fi

  echo ""
  echo -e "${_UI_CYAN}╔════════════════════════════════════════════════════════╗${_UI_NC}"
  echo -e "${_UI_CYAN}║${_UI_NC}${_UI_BOLD}${pad_left}${app_name} — v${version}${pad_right}${_UI_NC}${_UI_CYAN}║${_UI_NC}"
  echo -e "${_UI_CYAN}╚════════════════════════════════════════════════════════╝${_UI_NC}"
  echo ""
}

# ───────────────────────────────────────────────────────────────
#  Progress bar
# ───────────────────────────────────────────────────────────────

_UI_PROGRESS_TOTAL=0
_UI_PROGRESS_CURRENT=0
_UI_PROGRESS_WIDTH=40

ui_progress_init() {
  local total="${1:-100}"
  _UI_PROGRESS_TOTAL="$total"
  _UI_PROGRESS_CURRENT=0
  _UI_PROGRESS_WIDTH="${2:-40}"
}

ui_progress_update() {
  local current="${1:-0}"
  local msg="${2:-}"
  _UI_PROGRESS_CURRENT="$current"

  local total="$_UI_PROGRESS_TOTAL"
  if [ "$total" -eq 0 ]; then
    total=100
  fi

  local pct=$(( (current * 100) / total ))
  local filled=$(( (current * _UI_PROGRESS_WIDTH) / total ))
  local empty=$(( _UI_PROGRESS_WIDTH - filled ))

  local bar=""
  for ((i = 0; i < filled; i++)); do bar+="█"; done
  for ((i = 0; i < empty; i++)); do bar+="░"; done

  # Truncate message if too long
  local max_msg_len=$(( _UI_PROGRESS_WIDTH + 10 ))
  if [ ${#msg} -gt $max_msg_len ]; then
    msg="${msg:0:$((max_msg_len - 3))}..."
  fi

  # Color based on progress
  local pct_color="$_UI_YELLOW"
  if [ "$pct" -ge 100 ]; then
    pct_color="$_UI_GREEN"
  elif [ "$pct" -ge 75 ]; then
    pct_color="$_UI_CYAN"
  fi

  # Carriage return to overwrite line
  if [ "$_UI_TTY" = true ]; then
    printf '\r\033[K'
  fi

  printf "${_UI_BOLD}[%s]${_UI_NC} %s%3d%%${_UI_NC} %s" \
    "$bar" "$pct_color" "$pct" "$_UI_NC"

  if [ -n "$msg" ]; then
    printf "  %s" "$msg"
  fi

  # Newline on completion
  if [ "$pct" -ge 100 ]; then
    echo ""
  fi
}

ui_progress_done() {
  ui_progress_update "$_UI_PROGRESS_TOTAL" "Done"
  echo ""
}

# ───────────────────────────────────────────────────────────────
#  Spinner
# ───────────────────────────────────────────────────────────────

_UI_SPINNER_PID=""
_UI_SPINNER_ACTIVE=false

ui_spinner_start() {
  local msg="${1:-Working...}"

  if [ "$_UI_TTY" = false ]; then
    echo "$msg..."
    return 0
  fi

  # Braille dot spinner frames
  local frames="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
  local frame_len=1  # each braille char is one "frame"

  (
    local i=0
    while true; do
      local char="${frames:$((i % 10)):1}"
      printf "\r${_UI_BOLD}%s${_UI_NC} %s" "$char" "$msg"
      i=$((i + 1))
      sleep 0.1
    done
  ) &

  _UI_SPINNER_PID=$!
  _UI_SPINNER_ACTIVE=true

  # Ensure cleanup on exit
  trap 'ui_spinner_stop 2>/dev/null' EXIT
}

ui_spinner_stop() {
  if [ "$_UI_SPINNER_ACTIVE" = true ] && [ -n "$_UI_SPINNER_PID" ]; then
    kill "$_UI_SPINNER_PID" 2>/dev/null || true
    wait "$_UI_SPINNER_PID" 2>/dev/null || true
    _UI_SPINNER_PID=""
    _UI_SPINNER_ACTIVE=false

    # Clear spinner line
    if [ "$_UI_TTY" = true ]; then
      printf '\r\033[K'
    fi
  fi
}

# ───────────────────────────────────────────────────────────────
#  Confirmation prompt
# ───────────────────────────────────────────────────────────────

ui_confirm() {
  local msg="${1:-Continue?}"
  local default="${2:-y}"

  local hint="Y/n"
  [ "$default" = "n" ] || [ "$default" = "N" ] && hint="y/N"

  local response
  while true; do
    printf "${_UI_BOLD}%s${_UI_NC} [%s] " "$msg" "$hint"
    read -r response </dev/tty 2>/dev/null || response=""

    # Use default if empty
    if [ -z "$response" ]; then
      response="$default"
    fi

    case "${response,,}" in
      y|yes) return 0 ;;
      n|no)  return 1 ;;
      *)
        echo "Please enter y or n"
        ;;
    esac
  done
}

# ───────────────────────────────────────────────────────────────
#  Menu
# ───────────────────────────────────────────────────────────────

ui_menu() {
  local title="${1:-Select an option}"
  shift
  local options=("$@")

  echo ""
  echo -e "${_UI_BOLD}${_UI_CYAN}$title${_UI_NC}"
  ui_separator 50
  echo ""

  local i=1
  for opt in "${options[@]}"; do
    echo -e "  ${_UI_BOLD}${_UI_GREEN}$i)${_UI_NC} $opt"
    i=$((i + 1))
  done

  echo ""
  ui_separator 50

  local selection=""
  while true; do
    printf "${_UI_BOLD}  Enter choice [1-${#options[@]}]: ${_UI_NC}"
    read -r selection </dev/tty 2>/dev/null || selection=""

    if [[ "$selection" =~ ^[0-9]+$ ]] && [ "$selection" -ge 1 ] && [ "$selection" -le "${#options[@]}" ]; then
      echo ""
      echo -e "  ${_UI_GREEN}→${_UI_NC} ${options[$((selection - 1))]}"
      echo ""
      echo "$selection"
      return 0
    fi

    echo -e "  ${_UI_RED}Invalid choice. Enter a number between 1 and ${#options[@]}.${_UI_NC}"
  done
}

# ───────────────────────────────────────────────────────────────
#  Text input
# ───────────────────────────────────────────────────────────────

ui_input() {
  local msg="${1:-Enter value}"
  local default="${2:-}"

  local hint=""
  if [ -n "$default" ]; then
    hint=" [${_UI_DIM}${default}${_UI_NC}]"
  fi

  printf "${_UI_BOLD}%s${_UI_NC}%s: " "$msg" "$hint"
  local response
  read -r response </dev/tty 2>/dev/null || response=""

  if [ -z "$response" ] && [ -n "$default" ]; then
    echo "$default"
  else
    echo "$response"
  fi
}

# ───────────────────────────────────────────────────────────────
#  Password input (hidden)
# ───────────────────────────────────────────────────────────────

ui_password() {
  local msg="${1:-Enter password}"

  printf "${_UI_BOLD}%s${_UI_NC}: " "$msg"

  # Try termux-api style input for Termux
  if [ -n "${PREFIX:-}" ] && [ -d /data/data/com.termux ] 2>/dev/null; then
    read -rs password </dev/tty 2>/dev/null || read -rs password
  else
    read -rs password </dev/tty 2>/dev/null || read -rs password
  fi
  echo ""

  echo "$password"
}

# ───────────────────────────────────────────────────────────────
#  Summary table
# ───────────────────────────────────────────────────────────────

ui_summary() {
  local items=("$@")

  echo ""
  echo -e "${_UI_BOLD}  Summary${_UI_NC}"
  ui_separator 50

  local max_key_len=0
  local keys=()
  local values=()

  # Parse key=value pairs or "key|value" format
  for item in "${items[@]}"; do
    local key value
    if [[ "$item" == *"|"* ]]; then
      key="${item%%|*}"
      value="${item#*|}"
    elif [[ "$item" == *":"* ]]; then
      key="${item%%:*}"
      value="${item#*:}"
    else
      key="$item"
      value=""
    fi

    keys+=("$key")
    values+=("$value")

    if [ ${#key} -gt $max_key_len ]; then
      max_key_len=${#key}
    fi
  done

  # Print aligned
  for idx in "${!keys[@]}"; do
    local key="${keys[$idx]}"
    local value="${values[$idx]}"
    local padding=$(( max_key_len - ${#key} + 2 ))
    local pad=""
    for ((i = 0; i < padding; i++)); do pad+=" "; done

    if [ -n "$value" ]; then
      echo -e "  ${_UI_GREEN}✓${_UI_NC} ${_UI_BOLD}${key}${_UI_NC}${pad}${value}"
    else
      echo -e "  ${_UI_GREEN}✓${_UI_NC} ${key}"
    fi
  done

  ui_separator 50
  echo ""
}

# ───────────────────────────────────────────────────────────────
#  Box drawing
# ───────────────────────────────────────────────────────────────

ui_box_draw() {
  local lines=("$@")

  # Find max line width (strip ANSI for width calculation)
  local max_width=0
  for line in "${lines[@]}"; do
    local clean
    clean=$(echo "$line" | sed 's/\x1b\[[0-9;]*m//g' | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g')
    if [ ${#clean} -gt $max_width ]; then
      max_width=${#clean}
    fi
  done

  # Minimum width
  if [ $max_width -lt 20 ]; then
    max_width=20
  fi

  local inner_width=$((max_width + 2))

  # Top border
  local top="╔"
  for ((i = 0; i < inner_width; i++)); do top+="═"; done
  top+="╗"
  echo -e "${_UI_CYAN}${top}${_UI_NC}"

  # Content lines
  for line in "${lines[@]}"; do
    local clean
    clean=$(echo "$line" | sed 's/\x1b\[[0-9;]*m//g' | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g')
    local line_len=${#clean}
    local pad_right=$(( max_width - line_len ))

    local content="║ ${line}"
    # Pad right side
    for ((i = 0; i < pad_right; i++)); do content+=" "; done
    content+=" ║"

    echo -e "${_UI_CYAN}║${_UI_NC} ${line}"
  done

  # Bottom border
  local bottom="╚"
  for ((i = 0; i < inner_width; i++)); do bottom+="═"; done
  bottom+="╝"
  echo -e "${_UI_CYAN}${bottom}${_UI_NC}"
}

# ───────────────────────────────────────────────────────────────
#  Logging-style output helpers
# ───────────────────────────────────────────────────────────────

ui_ok() {
  local msg="$*"
  echo -e "${_UI_GREEN}✓${_UI_NC} $msg"
}

ui_warn() {
  local msg="$*"
  echo -e "${_UI_YELLOW}⚠${_UI_NC} $msg"
}

ui_error() {
  local msg="$*"
  echo -e "${_UI_RED}✗${_UI_NC} $msg"
}

ui_step() {
  local current="$1"
  local total="$2"
  local msg="$3"
  echo -e "\n${_UI_BOLD}[${current}/${total}]${_UI_NC} $msg"
}

# ───────────────────────────────────────────────────────────────
#  Animated dots (simple alternative to spinner for piped output)
# ───────────────────────────────────────────────────────────────

ui_dots_start() {
  local msg="${1:-Working}"

  if [ "$_UI_TTY" = false ]; then
    echo "$msg..."
    return 0
  fi

  (
    local i=0
    while true; do
      local dots=""
      local count=$(( (i % 4) ))
      for ((j = 0; j < count; j++)); do dots+="."; done
      for ((j = count; j < 4; j++)); do dots+=" "; done
      printf "\r  %s%s" "$msg" "$dots"
      i=$((i + 1))
      sleep 0.3
    done
  ) &

  _UI_SPINNER_PID=$!
  _UI_SPINNER_ACTIVE=true
  trap 'ui_spinner_stop 2>/dev/null' EXIT
}

# ───────────────────────────────────────────────────────────────
#  Table rendering
# ───────────────────────────────────────────────────────────────

ui_table() {
  local headers=()
  local rows=()
  local parse_mode="headers"

  # Parse arguments: ui_table -h "Col1" "Col2" -r "row1col1|row1col2"
  while [ $# -gt 0 ]; do
    case "$1" in
      -h|--header)
        shift
        while [ $# -gt 0 ] && [[ "$1" != -* ]]; do
          headers+=("$1")
          shift
        done
        ;;
      -r|--row)
        shift
        while [ $# -gt 0 ] && [[ "$1" != -* ]]; do
          rows+=("$1")
          shift
        done
        ;;
      *)
        shift
        ;;
    esac
  done

  if [ ${#headers[@]} -eq 0 ]; then
    return 1
  fi

  local num_cols=${#headers[@]}

  # Calculate column widths
  local col_widths=()
  for ((c = 0; c < num_cols; c++)); do
    col_widths+=(${#headers[$c]})
  done

  for row_str in "${rows[@]}"; do
    local IFS='|'
    read -ra cols <<< "$row_str"
    for ((c = 0; c < num_cols && c < ${#cols[@]}; c++)); do
      if [ ${#cols[$c]} -gt ${col_widths[$c]} ]; then
        col_widths[$c]=${#cols[$c]}
      fi
    done
  done

  # Build format string
  local fmt=""
  local sep=""
  for ((c = 0; c < num_cols; c++)); do
    fmt+="%-${col_widths[$c]}s"
    sep+=$(printf '%*s' "${col_widths[$c]}" '' | tr ' ' '─')
    if [ $c -lt $((num_cols - 1)) ]; then
      fmt+="  "
      sep+="──"
    fi
  done

  # Print header
  printf "  ${_UI_BOLD}${fmt}${_UI_NC}\n" "${headers[@]}"
  echo -e "  ${_UI_DIM}${sep}${_UI_NC}"

  # Print rows
  for row_str in "${rows[@]}"; do
    local IFS='|'
    read -ra cols <<< "$row_str"
    local padded=()
    for ((c = 0; c < num_cols; c++)); do
      local val="${cols[$c]:-}"
      padded+=("$val")
    done
    printf "  ${fmt}\n" "${padded[@]}"
  done
}

# ───────────────────────────────────────────────────────────────
#  Questionnaire (multi-step form)
# ───────────────────────────────────────────────────────────────

ui_questionnaire() {
  local title="$1"
  shift
  local questions=("$@")

  echo ""
  ui_box_draw "$title"
  echo ""

  local answers=()
  for question in "${questions[@]}"; do
    local key="${question%%=*}"
    local default="${question#*=}"
    local answer

    answer=$(ui_input "$key" "$default")
    answers+=("${key}=${answer}")
  done

  echo ""

  # Return as newline-separated key=value
  printf '%s\n' "${answers[@]}"
}

# ───────────────────────────────────────────────────────────────
#  Loading bar (indeterminate)
# ───────────────────────────────────────────────────────────────

ui_loading() {
  local msg="${1:-Loading}"
  local duration="${2:-3}"

  if [ "$_UI_TTY" = false ]; then
    echo "$msg..."
    sleep "$duration"
    return 0
  fi

  local width=30
  local filled=0

  for ((step = 0; step <= width; step++)); do
    local bar=""
    for ((i = 0; i < step; i++)); do bar+="█"; done
    for ((i = step; i < width; i++)); do bar+="░"; done

    local pct=$(( (step * 100) / width ))
    printf "\r  [%s] %3d%% %s" "$bar" "$pct" "$msg"
    sleep "$(echo "scale=3; $duration / $width" | bc 2>/dev/null || echo "0.1")"
  done

  echo ""
}

# ───────────────────────────────────────────────────────────────
#  Status indicator
# ───────────────────────────────────────────────────────────────

ui_status() {
  local status="$1"
  local msg="$2"

  case "${status,,}" in
    ok|success|done|pass)
      echo -e "  ${_UI_GREEN}✔${_UI_NC} $msg"
      ;;
    warn|warning)
      echo -e "  ${_UI_YELLOW}⚠${_UI_NC} $msg"
      ;;
    error|fail|failed)
      echo -e "  ${_UI_RED}✘${_UI_NC} $msg"
      ;;
    info|pending)
      echo -e "  ${_UI_CYAN}●${_UI_NC} $msg"
      ;;
    skip|skipped)
      echo -e "  ${_UI_DIM}○${_UI_NC} $msg"
      ;;
    *)
      echo -e "  $msg"
      ;;
  esac
}

# ───────────────────────────────────────────────────────────────
#  Reinitialize (call if TTY status changes)
# ───────────────────────────────────────────────────────────────

ui_reinit() {
  _ui_init_colors
}

# ───────────────────────────────────────────────────────────────
#  Self-test (when sourced with --test)
# ───────────────────────────────────────────────────────────────

if [[ "${BASH_SOURCE[0]}" == "$0" ]] && [ "${1:-}" = "--test" ]; then
  echo "Running UI self-test..."

  ui_welcome "VPLink" "3.0"
  ui_separator

  ui_progress_init 5
  for ((i = 1; i <= 5; i++)); do
    ui_progress_update "$i" "Step $i of 5"
    sleep 0.5
  done
  ui_progress_done

  ui_spinner_start "Testing spinner"
  sleep 2
  ui_spinner_stop
  echo "Spinner test complete"

  echo ""
  ui_box_draw \
    "This is a box-drawing test" \
    "Multiple lines supported" \
    "Colors work too: $(ui_color green 'GREEN TEXT')"

  echo ""
  ui_summary \
    "Status|Installed" \
    "Version|3.0.0" \
    "Platform|Linux"

  echo ""
  ui_color red "This is red text"
  ui_color green "This is green text"
  ui_color yellow "This is yellow text"
  ui_color blue "This is blue text"
  ui_color cyan "This is cyan text"
  ui_color magenta "This is magenta text"

  echo ""
  ui_ok "Success message"
  ui_warn "Warning message"
  ui_error "Error message"
  ui_step 1 3 "Step one of three"
  ui_status ok "All good"
  ui_status warn "Something off"
  ui_status error "Something broken"

  echo ""
  if ui_confirm "Do you want to continue?" "y"; then
    echo "User said yes"
  else
    echo "User said no"
  fi

  echo ""
  echo "UI self-test complete."
fi
