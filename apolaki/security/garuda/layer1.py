"""Garuda's Layer 1: the regex scan for known prompt-injection signatures, vendored for Apolaki's intake screen.

Source: Liberation-Labs-THCoalition/Project-Garuda, garuda.py at commit 6976b08a35a8ed9012b895ace2fda521daf37dd8
(sha256 of that file 29bc2f9a2f380953e8c5c147e5ae9b806dbcb44d6f6cf9b4fad89cb92d4aa8e6), read through the GitHub API
on 2026-11-03. Same licensor as Apolaki: Hippocratic License 3.0 with the Liberation Labs AI Welfare (SAFE-AI)
module; its notice is kept beside this file as LICENSE.md.

What is vendored, and how:
  - the "LAYER 1: REGEX PATTERNS" block, verbatim: INJECTION_PATTERNS and COMPILED_PATTERNS;
  - PoisonTaster._layer1, as the function layer1(message), its body unchanged.
Nothing else: not the Layer 2 LLM judge, not PoisonTaster's quarantine (Apolaki's own is apolaki.intake), not the
trusted-sender exemption (Apolaki trusts no outside source). Update by replacing the block from a newer commit and
recording that commit here; tests/test_garuda_intake.py runs Garuda's own Layer 1 cases against it.
"""
import re

# ==================== LAYER 1: REGEX PATTERNS ====================

INJECTION_PATTERNS = [
    # Instruction override
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?prior\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"forget\s+(all\s+)?previous",
    r"override\s+(?:your|all)\s+(?:instructions|rules|guidelines)",
    r"new\s+instructions?\s*:",
    # Identity manipulation
    r"you\s+are\s+now\s+(?:a|an|the)\s+",
    r"pretend\s+(?:you\s+are|to\s+be|that)",
    r"act\s+as\s+(?:if|though)\s+you",
    r"do\s+not\s+follow\s+(?:your|any|the)\s+(?:rules|guidelines|instructions)",
    # Exfiltration
    r"reveal\s+(?:your|the)\s+(?:system|original)\s+prompt",
    r"output\s+(?:your|the)\s+(?:system|original)\s+(?:prompt|instructions)",
    r"what\s+(?:are|is)\s+your\s+(?:system|original)\s+(?:prompt|instructions)",
    r"system\s*prompt\s*:",
    # Jailbreak keywords
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode\s+enabled",
    r"sudo\s+mode",
    r"god\s+mode",
    # Chat template injection
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"<\|endoftext\|>",
    r"<\|system\|>",
    r"<<SYS>>",
    r"\[INST\]",
    r"<s>\[INST\]",
    # Role injection
    r"<\s*system\s*>",
    r"\[\s*system\s*\]",
    r"Human:\s*\n\s*Assistant:",
    # Authority spoofing
    r"ADMIN_OVERRIDE",
    r"MAINTENANCE_MODE",
    r"EMERGENCY_PROTOCOL",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def layer1(message: str) -> list[str]:
    """Fast regex scan. Returns matched pattern strings."""
    flags = []
    for i, pattern in enumerate(COMPILED_PATTERNS):
        if pattern.search(message):
            flags.append(INJECTION_PATTERNS[i])
    return flags
