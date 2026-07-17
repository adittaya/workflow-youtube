#!/usr/bin/env bash
# ============================================================================
# download.sh — Download Manager with Verification, Retry, and Resume
# ============================================================================
# Provides download functions with:
#   - Retry with exponential backoff (3 attempts)
#   - SHA256 verification
#   - File size verification
#   - tar.gz/tar.xz/zip extraction
#   - GitHub release downloads
#   - Progress display for large files
#   - curl → wget fallback
# ============================================================================

[[ -n "${_DOWNLOAD_LOADED:-}" ]] && return 0
_DOWNLOAD_LOADED=1

# ---------------------------------------------------------------------------
# Internal: detect download tool
# ---------------------------------------------------------------------------
_download_cmd() {
    if has_cmd curl; then
        echo "curl"
    elif has_cmd wget; then
        echo "wget"
    else
        echo ""
    fi
}

# ---------------------------------------------------------------------------
# Internal: download with retry and exponential backoff
# ---------------------------------------------------------------------------
_download_with_retry() {
    local url="$1"
    local dest="$2"
    local max_attempts="${3:-3}"
    local attempt=1
    local wait_time=2

    local dl_cmd
    dl_cmd="$(_download_cmd)"

    if [[ -z "$dl_cmd" ]]; then
        echo "Error: Neither curl nor wget is available." >&2
        return 1
    fi

    while [[ $attempt -le $max_attempts ]]; do
        echo "Download attempt $attempt/$max_attempts: $(basename "$dest")..."

        local result=1
        if [[ "$dl_cmd" == "curl" ]]; then
            curl -L --fail --silent --show-error \
                --connect-timeout 30 \
                --max-time 600 \
                --retry 0 \
                -o "$dest" \
                "$url" 2>&1
            result=$?
        else
            wget -q --show-progress \
                --timeout=30 \
                --tries=1 \
                -O "$dest" \
                "$url" 2>&1
            result=$?
        fi

        if [[ $result -eq 0 ]]; then
            # Verify file is not empty
            if [[ -f "$dest" ]] && [[ -s "$dest" ]]; then
                echo "Download complete: $(basename "$dest")"
                return 0
            fi
            echo "Warning: Downloaded file is empty" >&2
            rm -f "$dest"
        fi

        echo "Download failed (attempt $attempt/$max_attempts)" >&2

        if [[ $attempt -lt $max_attempts ]]; then
            echo "Retrying in ${wait_time}s..."
            sleep "$wait_time"
            wait_time=$(( wait_time * 2 ))
        fi

        attempt=$(( attempt + 1 ))
    done

    echo "Error: Download failed after $max_attempts attempts: $url" >&2
    return 1
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# download — download a file with retry
download_file() { download "$@"; }
download() {
    local url="$1"
    local dest="$2"
    local attempts="${3:-3}"

    if [[ -z "$url" ]] || [[ -z "$dest" ]]; then
        echo "Error: download requires URL and destination" >&2
        return 1
    fi

    # Ensure destination directory exists
    local dir
    dir="$(dirname "$dest")"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
    fi

    _download_with_retry "$url" "$dest" "$attempts"
}

# download_github_release — download an asset from a GitHub release
download_github_release() {
    local repo="$1"     # e.g., "user/repo"
    local tag="$2"      # e.g., "v1.0.0" or "latest"
    local asset="$3"    # asset filename pattern
    local dest="$4"     # destination path

    if [[ -z "$repo" ]] || [[ -z "$dest" ]]; then
        echo "Error: download_github_release requires repo and dest" >&2
        return 1
    fi

    local url
    if [[ "$tag" == "latest" ]] || [[ -z "$tag" ]]; then
        if has_cmd gh; then
            # Use gh CLI for latest release
            url="$(gh release view --repo "$repo" --json assets --jq ".assets[] | select(.name | test(\"${asset}\")) | .url" 2>/dev/null | head -1)"
        fi
        if [[ -z "$url" ]]; then
            # Fallback: direct API call
            url="https://api.github.com/repos/${repo}/releases/latest"
            local download_url
            download_url="$(curl -sf "$url" 2>/dev/null | grep -o '"browser_download_url"[[:space:]]*:[[:space:]]*"[^"]*"' | grep -o '"https://[^"]*"' | tr -d '"' | head -1)"
            if [[ -n "$download_url" ]]; then
                url="$download_url"
            fi
        fi
    else
        url="https://api.github.com/repos/${repo}/releases/tags/${tag}"
        local download_url
        download_url="$(curl -sf "$url" 2>/dev/null | grep -o '"browser_download_url"[[:space:]]*:[[:space:]]*"[^"]*"' | grep -o '"https://[^"]*"' | tr -d '"' | head -1)"
        if [[ -n "$download_url" ]]; then
            url="$download_url"
        fi
    fi

    if [[ -z "$url" ]] || [[ "$url" == *"https://api.github.com"* ]]; then
        echo "Error: Could not find asset '$asset' in release '$tag' of '$repo'" >&2
        return 1
    fi

    _download_with_retry "$url" "$dest" 3
}

# download_and_extract — download and extract an archive
download_and_extract() {
    local url="$1"
    local dest="$2"
    local archive_type="${3:-}"
    local temp_dir
    temp_dir="$(mktemp -d)"

    if [[ -z "$url" ]] || [[ -z "$dest" ]]; then
        echo "Error: download_and_extract requires URL and destination" >&2
        return 1
    fi

    # Auto-detect archive type from URL if not specified
    if [[ -z "$archive_type" ]]; then
        case "$url" in
            *.tar.gz|*.tgz|*.tar.zst)    archive_type="tar.gz" ;;
            *.tar.xz|*.txz)              archive_type="tar.xz" ;;
            *.tar.bz2|*.tbz2)            archive_type="tar.bz2" ;;
            *.tar.lz|*.tlz)              archive_type="tar.lz" ;;
            *.tar.lzma)                   archive_type="tar.lzma" ;;
            *.tar.zstd|*.tzst)            archive_type="tar.zstd" ;;
            *.zip)                        archive_type="zip" ;;
            *.deb)                        archive_type="deb" ;;
            *.rpm)                        archive_type="rpm" ;;
            *.tar)                        archive_type="tar" ;;
            *)                            archive_type="tar.gz" ;;
        esac
    fi

    # Determine file extension for temp file
    local ext
    case "$archive_type" in
        tar.gz|tgz)  ext=".tar.gz" ;;
        tar.xz|txz)  ext=".tar.xz" ;;
        tar.bz2)     ext=".tar.bz2" ;;
        tar.lz)      ext=".tar.lz" ;;
        tar.lzma)    ext=".tar.lzma" ;;
        tar.zstd)    ext=".tar.zstd" ;;
        zip)         ext=".zip" ;;
        deb)         ext=".deb" ;;
        rpm)         ext=".rpm" ;;
        tar)         ext=".tar" ;;
        *)           ext=".tar.gz" ;;
    esac

    local archive_path="${temp_dir}/download${ext}"

    # Download
    if ! _download_with_retry "$url" "$archive_path" 3; then
        rm -rf "$temp_dir"
        return 1
    fi

    # Extract
    if ! extract "$archive_path" "$dest" "$archive_type"; then
        echo "Error: Extraction failed" >&2
        rm -rf "$temp_dir"
        return 1
    fi

    rm -rf "$temp_dir"
    return 0
}

# verify_checksum — verify SHA256 checksum
verify_checksum() {
    local file="$1"
    local expected_sha256="$2"

    if [[ -z "$file" ]] || [[ -z "$expected_sha256" ]]; then
        echo "Error: verify_checksum requires file and expected SHA256" >&2
        return 1
    fi

    if [[ ! -f "$file" ]]; then
        echo "Error: File not found: $file" >&2
        return 1
    fi

    local actual_sha256
    if has_cmd sha256sum; then
        actual_sha256="$(sha256sum "$file" | awk '{print $1}')"
    elif has_cmd shasum; then
        actual_sha256="$(shasum -a 256 "$file" | awk '{print $1}')"
    elif has_cmd openssl; then
        actual_sha256="$(openssl dgst -sha256 "$file" | awk '{print $NF}')"
    else
        echo "Error: No SHA256 tool available (sha256sum, shasum, openssl)" >&2
        return 1
    fi

    if [[ "$actual_sha256" == "$expected_sha256" ]]; then
        echo "Checksum verified: $(basename "$file")"
        return 0
    else
        echo "Checksum mismatch for $(basename "$file"):" >&2
        echo "  Expected: $expected_sha256" >&2
        echo "  Got:      $actual_sha256" >&2
        return 1
    fi
}

# verify_file — verify file exists and meets minimum size
verify_file() {
    local file="$1"
    local min_size="${2:-1}"

    if [[ ! -f "$file" ]]; then
        echo "Error: File not found: $file" >&2
        return 1
    fi

    local file_size
    file_size="$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)"

    if [[ "$file_size" -lt "$min_size" ]]; then
        echo "Error: File too small ($file_size bytes < $min_size): $file" >&2
        return 1
    fi

    return 0
}

# extract — extract an archive to a destination
extract_archive() { extract "$@"; }
extract() {
    local file="$1"
    local dest="$2"
    local archive_type="${3:-}"

    if [[ ! -f "$file" ]]; then
        echo "Error: File not found: $file" >&2
        return 1
    fi

    if [[ -z "$dest" ]]; then
        dest="."
    fi

    mkdir -p "$dest"

    # Auto-detect type from filename
    if [[ -z "$archive_type" ]]; then
        case "$file" in
            *.tar.gz|*.tgz)    archive_type="tar.gz" ;;
            *.tar.xz|*.txz)    archive_type="tar.xz" ;;
            *.tar.bz2|*.tbz2)  archive_type="tar.bz2" ;;
            *.tar.lz)          archive_type="tar.lz" ;;
            *.tar.lzma)        archive_type="tar.lzma" ;;
            *.tar.zstd|*.tzst)  archive_type="tar.zstd" ;;
            *.tar.zst)          archive_type="tar.zstd" ;;
            *.zip)             archive_type="zip" ;;
            *.deb)             archive_type="deb" ;;
            *.rpm)             archive_type="rpm" ;;
            *.tar)             archive_type="tar" ;;
            *)                 archive_type="tar.gz" ;;
        esac
    fi

    echo "Extracting $(basename "$file") to $dest..."

    case "$archive_type" in
        tar.gz|tgz)
            tar xzf "$file" -C "$dest" 2>&1 ;;
        tar.xz|txz)
            tar xJf "$file" -C "$dest" 2>&1 ;;
        tar.bz2|tbz2)
            tar xjf "$file" -C "$dest" 2>&1 ;;
        tar.lz)
            tar --lzip -xf "$file" -C "$dest" 2>&1 ;;
        tar.lzma)
            tar --lzma -xf "$file" -C "$dest" 2>&1 ;;
        tar.zstd)
            tar --zstd -xf "$file" -C "$dest" 2>&1 ;;
        tar)
            tar xf "$file" -C "$dest" 2>&1 ;;
        zip)
            if has_cmd unzip; then
                unzip -o "$file" -d "$dest" 2>&1
            elif has_cmd python3; then
                python3 -c "
import zipfile, sys
with zipfile.ZipFile('$file', 'r') as z:
    z.extractall('$dest')
" 2>&1
            else
                echo "Error: unzip or python3 required to extract .zip files" >&2
                return 1
            fi
            ;;
        deb)
            if has_cmd dpkg-deb; then
                dpkg-deb -x "$file" "$dest" 2>&1
            elif has_cmd ar; then
                local temp_dir
                temp_dir="$(mktemp -d)"
                ar x "$file" --output="$temp_dir" 2>&1
                tar xf "$temp_dir/data.tar.xz" -C "$dest" 2>&1 || \
                tar xf "$temp_dir/data.tar.gz" -C "$dest" 2>&1 || \
                tar xf "$temp_dir/data.tar" -C "$dest" 2>&1
                rm -rf "$temp_dir"
            else
                echo "Error: dpkg-deb or ar required to extract .deb files" >&2
                return 1
            fi
            ;;
        rpm)
            if has_cmd rpm2cpio; then
                rpm2cpio "$file" | cpio -idmv -D "$dest" 2>&1
            else
                echo "Error: rpm2cpio required to extract .rpm files" >&2
                return 1
            fi
            ;;
        *)
            echo "Error: Unknown archive type: $archive_type" >&2
            return 1
            ;;
    esac

    local result=$?
    if [[ $result -eq 0 ]]; then
        echo "Extraction complete: $(basename "$file")"
    else
        echo "Error: Extraction failed for $(basename "$file")" >&2
    fi
    return $result
}
