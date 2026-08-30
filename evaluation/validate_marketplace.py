#!/usr/bin/env python3
"""Structural + hygiene validator for the marketplace.

Checks the manifest is well-formed with exactly one entrypoint, every listed
skill folder has a spec-valid SKILL.md (name == folder, license present, closed
frontmatter key set), every checks.py compiles and exposes run(), and the bundled
report schema is itself valid JSON Schema. Run: python3 evaluation/validate_marketplace.py
Exits non-zero on any failure.
"""
import json
import os
import py_compile
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ALLOWED_FRONTMATTER = {"name", "description", "license", "allowed-tools",
                       "version", "metadata", "compatibility"}
errors, warnings = [], []


def _frontmatter(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return yaml.safe_load(text[3:end])


def main():
    man_path = os.path.join(ROOT, "marketplace.json")
    if not os.path.isfile(man_path):
        print("FAIL: marketplace.json missing")
        return 1
    man = json.load(open(man_path, encoding="utf-8"))

    entrypoints = [s for s in man.get("skills", []) if s.get("entrypoint")]
    if len(entrypoints) != 1:
        errors.append(f"expected exactly 1 entrypoint, found {len(entrypoints)}")

    for s in man.get("skills", []):
        sid = s.get("id", "?")
        folder = os.path.join(ROOT, s.get("path", ""))
        if not os.path.isdir(folder):
            errors.append(f"{sid}: folder {s.get('path')} missing")
            continue
        skill_md = os.path.join(folder, "SKILL.md")
        if not os.path.isfile(skill_md):
            errors.append(f"{sid}: SKILL.md missing")
            continue
        fm = _frontmatter(skill_md)
        if not fm:
            errors.append(f"{sid}: SKILL.md has no YAML frontmatter")
            continue
        if fm.get("name") != sid:
            errors.append(f"{sid}: frontmatter name '{fm.get('name')}' != skill id / folder")
        if os.path.basename(folder) != sid:
            errors.append(f"{sid}: folder name != skill id")
        if not fm.get("description"):
            errors.append(f"{sid}: frontmatter missing description")
        if not fm.get("license"):
            errors.append(f"{sid}: frontmatter missing license")
        bad_keys = set(fm) - ALLOWED_FRONTMATTER
        if bad_keys:
            warnings.append(f"{sid}: unexpected frontmatter keys {sorted(bad_keys)}")

        checks = os.path.join(folder, "scripts", "checks.py")
        if sid == man["entrypoint"]:
            audit = os.path.join(folder, "scripts", "audit.py")
            if not os.path.isfile(audit):
                errors.append(f"{sid}: entrypoint missing scripts/audit.py")
            else:
                try:
                    py_compile.compile(audit, doraise=True)
                except py_compile.PyCompileError as e:
                    errors.append(f"{sid}: audit.py does not compile: {e}")
        elif os.path.isfile(checks):
            try:
                py_compile.compile(checks, doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"{sid}: checks.py does not compile: {e}")
            if "def run(" not in open(checks, encoding="utf-8").read():
                errors.append(f"{sid}: checks.py has no run() function")
        else:
            errors.append(f"{sid}: missing scripts/checks.py")

    # bundled report schema must be valid JSON Schema
    try:
        import jsonschema
        schema = json.load(open(os.path.join(ROOT, "common", "schema.json"), encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    except Exception as e:
        errors.append(f"common/schema.json invalid: {e}")

    for w in warnings:
        print("WARN:", w)
    for e in errors:
        print("FAIL:", e)
    if errors:
        return 1
    print(f"OK: marketplace valid — {len(man['skills'])} skills, 1 entrypoint, all SKILL.md + scripts sound.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
