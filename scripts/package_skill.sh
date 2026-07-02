#!/usr/bin/env bash
# 将技能打包为自包含 zip，内嵌 lib/ 依赖
# 用法：bash scripts/package_skill.sh [output_dir]
# 默认输出：./packages/

set -euo pipefail

SKILLS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${1:-${SKILLS_DIR}/packages}"
mkdir -p "$OUTPUT_DIR"

# 各技能需要的 lib 模块
declare -A SKILL_LIB_DEPS
SKILL_LIB_DEPS["vocab-anki"]="coca.py lemmatize.py ankiconnect.py utils.py sync_anki.py SHARED_WORKFLOW.md"
SKILL_LIB_DEPS["vocab-book"]="coca.py lemmatize.py ankiconnect.py utils.py sync_anki.py SHARED_WORKFLOW.md"
SKILL_LIB_DEPS["vocab-list"]="coca.py lemmatize.py"

for skill in "${!SKILL_LIB_DEPS[@]}"; do
    echo "打包: ${skill}..."

    TMPDIR="$(mktemp -d)"
    SKILL_DIR="${TMPDIR}/${skill}"

    # 1. 复制技能专属文件（排除符号链接和缓存）
    rsync -a \
        --exclude='__pycache__' --exclude='.pytest_cache' \
        --exclude='.venv' --exclude='.git' --exclude='*.pyc' \
        --exclude='lib' \
        "${SKILLS_DIR}/${skill}/" "${SKILL_DIR}/"

    # 2. 创建 lib/ 目录并复制所需模块
    mkdir -p "${SKILL_DIR}/lib/data/bnc_coca" "${SKILL_DIR}/lib/scripts"

    # 2a. __init__.py + 核心模块
    cp "${SKILLS_DIR}/lib/__init__.py" "${SKILL_DIR}/lib/__init__.py"
    for mod in ${SKILL_LIB_DEPS[$skill]}; do
        if [ -f "${SKILLS_DIR}/lib/${mod}" ]; then
            cp "${SKILLS_DIR}/lib/${mod}" "${SKILL_DIR}/lib/${mod}"
        fi
    done

    # 2b. 复制 scripts/ 共享脚本
    for script in match_sentences.py translate_deepl.py audit_deck.py; do
        src="${SKILLS_DIR}/lib/scripts/${script}"
        dst="${SKILL_DIR}/lib/scripts/${script}"
        [ -f "$src" ] && cp "$src" "$dst"
    done
    # scripts/__init__.py
    [ -f "${SKILLS_DIR}/lib/scripts/__init__.py" ] && \
        cp "${SKILLS_DIR}/lib/scripts/__init__.py" "${SKILL_DIR}/lib/scripts/__init__.py"

    # 3. 复制数据文件
    cp -r "${SKILLS_DIR}/lib/data/bnc_coca/"* "${SKILL_DIR}/lib/data/bnc_coca/"
    cp "${SKILLS_DIR}/lib/data/cmudict.dict" "${SKILL_DIR}/lib/data/cmudict.dict"

    # 4. 创建 zip
    cd "${TMPDIR}"
    zip -qr "${OUTPUT_DIR}/${skill}.zip" "${skill}/"
    cd "${SKILLS_DIR}"

    rm -rf "${TMPDIR}"
    echo "  -> ${OUTPUT_DIR}/${skill}.zip"
done

echo "完成。输出目录: ${OUTPUT_DIR}"
