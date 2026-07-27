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
        Check if a section with the given header exists.
        Section is defined as header line followed by indented lines.
        """
        lines = config.splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.strip() == header:
                # Check if next lines are indented (Cisco/Huawei style)
                # Or just check if header exists for flat configs
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # If next line is indented or non-empty and not a new global section
                    if (
                        next_line.startswith(" ")
                        or next_line.startswith("\t")
                        or next_line.strip()
                    ):
                        found = True
                        break
                else:
                    # Header is the last line
                    found = True
                    break

        return found, f"Section '{header}' {'found' if found else 'not found'}"

    def _check_section_contains(self, config: str, pattern_str: str) -> tuple:
        """
        Check if a section contains specific content.
        pattern_str should be 'header\ncontent'.
        """
        parts = pattern_str.split("\n", 1)
        if len(parts) != 2:
            return (
                False,
                "Invalid pattern format for section_contains: expected 'header\\ncontent'",
            )

        header, content = parts

        lines = config.splitlines()
        in_section = False
        section_lines = []

        for line in lines:
            if line.strip() == header:
                in_section = True
                section_lines = [line]
            elif in_section:
                if line.startswith(" ") or line.startswith("\t") or not line.strip():
                    section_lines.append(line)
                else:
                    # End of section
                    break

        section_text = "\n".join(section_lines)
        found = _normalize_whitespace(content) in _normalize_whitespace(section_text)
        return found, f"Content in section {'found' if found else 'not found'}"

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
