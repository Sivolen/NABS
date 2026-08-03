import re
from typing import List, Dict, Any


def _normalize_whitespace(text: str) -> str:
    """
    Collapse any run of whitespace (spaces, tabs, line wraps/newlines) into
    a single space. Lets 'contains'/'section_contains' match text typed as
    one logical line/block even if the device's actual output wraps long
    lines (e.g. long ACL rules) or uses slightly different indentation -
    without the person having to hand-write a regex with \\s+ everywhere.
    """
    return re.sub(r"\s+", " ", text).strip()


KNOWN_RULE_TYPES = (
    "contains",
    "not_contains",
    "equals",
    "starts_with",
    "ends_with",
    "regex",
    "section_exists",
    "section_contains",
    "count",
)


def validate_pattern_format(rule_type: str, pattern: str):
    """
    Format-only check: is this pattern well-formed for this rule_type?
    Doesn't check whether it would actually match anything - just whether
    it's syntactically usable, so mistakes (missing second line, bad regex,
    non-numeric count) get caught when the rule is saved, not the first
    time it's ever run against a real device.

    Returns an error message string, or None if the pattern looks fine.
    """
    if rule_type not in KNOWN_RULE_TYPES:
        return f"Unknown rule type: {rule_type}"
    if not pattern or not pattern.strip():
        return "Pattern cannot be empty"

    if rule_type == "regex":
        try:
            re.compile(pattern)
        except re.error as e:
            return f"Invalid regex: {e}"

    elif rule_type == "section_contains":
        parts = pattern.split("\n", 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            return (
                "section_contains needs two lines: the section header on "
                "line 1, the required content on line 2 (and beyond)"
            )

    elif rule_type == "count":
        parts = pattern.split("\n", 1)
        if len(parts) != 2 or not parts[0].strip():
            return (
                "count needs two lines: the text to count on line 1, the "
                "minimum number of occurrences on line 2"
            )
        try:
            int(parts[1].strip())
        except ValueError:
            return "count's second line must be a whole number (minimum occurrences)"

    return None


class ValidationEngine:
    """
    Pure validation engine. No DB dependencies.
    Validates a configuration string against a list of rules.
    """

    def evaluate_rule(self, rule: Dict[str, Any], config: str) -> Dict[str, Any]:
        """
        Evaluate a single rule against the configuration.
        Returns a dict with 'passed' (bool), 'message' (str).
        """
        rule_type = rule.get("rule_type")
        pattern = rule.get("pattern", "")

        try:
            if rule_type == "contains":
                result = _normalize_whitespace(pattern) in _normalize_whitespace(config)
                msg = (
                    f"Found pattern: {pattern}"
                    if result
                    else f"Pattern not found: {pattern}"
                )
            elif rule_type == "not_contains":
                result = _normalize_whitespace(pattern) not in _normalize_whitespace(
                    config
                )
                msg = (
                    f"Pattern correctly absent: {pattern}"
                    if result
                    else f"Pattern found (should be absent): {pattern}"
                )
            elif rule_type == "equals":
                lines = [l.strip() for l in config.splitlines()]
                result = pattern.strip() in lines
                msg = (
                    "Matching config line found"
                    if result
                    else "No config line matches exactly"
                )
            elif rule_type == "starts_with":
                lines = [l.strip() for l in config.splitlines()]
                result = any(l.startswith(pattern) for l in lines)
                msg = (
                    "Matching config line found"
                    if result
                    else "No config line starts with pattern"
                )
            elif rule_type == "ends_with":
                lines = [l.strip() for l in config.splitlines()]
                result = any(l.endswith(pattern) for l in lines)
                msg = (
                    "Matching config line found"
                    if result
                    else "No config line ends with pattern"
                )
            elif rule_type == "regex":
                try:
                    result = bool(re.search(pattern, config, re.MULTILINE | re.DOTALL))
                    msg = (
                        f"Regex matched: {pattern}"
                        if result
                        else f"Regex not matched: {pattern}"
                    )
                except re.error as e:
                    return {"passed": False, "message": f"Invalid regex: {e}"}
            elif rule_type == "section_exists":
                result, msg = self._check_section_exists(config, pattern)
            elif rule_type == "section_contains":
                result, msg = self._check_section_contains(config, pattern)
            elif rule_type == "count":
                result, msg = self._check_count(config, pattern)
            else:
                return {"passed": False, "message": f"Unknown rule type: {rule_type}"}

            return {"passed": result, "message": msg}

        except Exception as e:
            return {"passed": False, "message": f"Error evaluating rule: {str(e)}"}

    def _check_section_exists(self, config: str, header: str) -> tuple:
        """
        Check if a section header line exists in the config at all - it
        doesn't need any indented children under it (a bare 'interface
        Loopback0' with nothing configured under it still counts as the
        section existing).
        """
        header = header.strip()
        found = any(line.strip() == header for line in config.splitlines())
        return found, f"Section '{header}' {'found' if found else 'not found'}"

    def _check_section_contains(self, config: str, pattern_str: str) -> tuple:
        """
        Check if a section contains specific content.
        Works for both indented sections (Cisco style) and flat sections (ACL).
        pattern_str should be 'header\ncontent'.
        """
        parts = pattern_str.split("\n", 1)
        if len(parts) != 2:
            return (
                False,
                "Invalid pattern format for section_contains: expected 'header\ncontent'",
            )

        header, content = parts
        header = header.strip()
        content_normalized = _normalize_whitespace(content)

        lines = config.splitlines()
        section_lines = []
        found_header = False

        # Заголовки, которые начинают новую секцию
        section_headers = [
            "acl number",
            "interface",
            "ip access-list",
            "route-map",
            "policy-map",
            "class-map",
            "vlan",
            "spanning-tree",
            "bridge-domain",
            "evpn vpn-instance",
            "traffic classifier",
            "traffic behavior",
            "traffic policy",
        ]

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Нашли заголовок секции
            if stripped == header:
                found_header = True
                section_lines = [line]
                continue

            if found_header:
                # Пустые строки внутри секции сохраняем
                if not stripped:
                    section_lines.append(line)
                    continue

                # Проверяем, не началась ли новая секция
                is_new_section = False
                for sh in section_headers:
                    if stripped.startswith(sh) and stripped != header:
                        is_new_section = True
                        break

                # Если это новая секция - останавливаемся
                if is_new_section:
                    break

                # Если строка имеет отступ - это часть секции
                if line.startswith(" ") or line.startswith("	"):
                    section_lines.append(line)
                # Если строка начинается с rule/permit/deny (ACL) - часть секции
                elif stripped.startswith("rule") or stripped.startswith("permit") or stripped.startswith("deny"):
                    section_lines.append(line)
                # Если строка начинается с "description" (часто внутри ACL) - часть секции
                elif stripped.startswith("description"):
                    section_lines.append(line)
                # Если строка без отступа, но не является новым заголовком
                elif not line.startswith(" ") and not line.startswith("	"):
                    # Для плоских конфигов (ACL) продолжаем собирать
                    section_lines.append(line)
                else:
                    # Иначе - секция закончилась
                    break

        section_text = "\n".join(section_lines)
        section_normalized = _normalize_whitespace(section_text)
        found = content_normalized in section_normalized

        return found, f"Content in section '{header}' {'found' if found else 'not found'}"

    def _check_count(self, config: str, pattern_str: str) -> tuple:
        """
        Check if a pattern appears at least N times.
        pattern_str should be 'pattern\nmin_count'.
        """
        parts = pattern_str.split("\n", 1)
        if len(parts) != 2:
            return (
                False,
                "Invalid pattern format for count: expected 'pattern\\nmin_count'",
            )

        pattern, min_count_str = parts
        try:
            min_count = int(min_count_str.strip())
        except ValueError:
            return False, "Invalid min_count value"

        count = config.count(pattern)
        passed = count >= min_count
        return passed, f"Found {count} occurrences (min: {min_count})"
