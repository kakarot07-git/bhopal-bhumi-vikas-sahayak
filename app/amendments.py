"""Amendments made after the consolidated copy (6 March 2025).

The rules file stops at 6 March 2025. Known later changes are kept here, with
their source, so the tool can tell the clerk which version an answer uses.

IMPORTANT: the official gazette text of the 28 Aug 2026 amendment was not in the
data pack. The entry below is based on a secondary summary (link given). The tool
always shows it as "verify against the gazette".
"""

AMENDMENTS = [
    {
        "id": "2026-08-28-rule-2-5-c",
        "date": "28 August 2026",
        "rule": "2",
        "clause": "2(5)(c)",
        "affects_rules": ["2", "12", "14"],
        "applies_to": {"max_plot_area_sqm": 500},
        "summary_en": (
            "Rule 2(5)(c) was amended on 28 August 2026. For plots up to 500 sq m, the local authority may permit "
            "construction or reconstruction where it conforms to the existing land use in the approved Development Plan. "
            "Such work does not need separate development permission under Rule 2(5)(a), provided it meets the "
            "Development Plan's norms."
        ),
        "summary_hi": (
            "28 अगस्त 2026 को नियम 2(5)(c) में संशोधन हुआ। 500 वर्ग मीटर तक के प्लॉट पर, यदि निर्माण स्वीकृत विकास योजना "
            "(Development Plan) के मौजूदा भूमि उपयोग के अनुरूप है, तो स्थानीय निकाय निर्माण/पुनर्निर्माण की अनुमति दे सकता है। "
            "ऐसे मामलों में नियम 2(5)(a) के तहत अलग से विकास अनुमति (development permission) की ज़रूरत नहीं है, बशर्ते विकास योजना के मानदंड पूरे हों।"
        ),
        "quoted_words": "the local authority may permit construction or reconstruction on plots having an area of up to 500 sq. metres",
        "source": "TeamLease RegTech summary (secondary source - official gazette text not in the data pack)",
        "source_url": "https://teamleaseregtech.com/updates/article/59469/government-of-madhya-pradesh-amendment-to-land-development-rules",
        "status": "secondary-source",
    },
]


def amendments_for_rules(rule_ids: list[str]) -> list[dict]:
    ids = set(rule_ids)
    return [a for a in AMENDMENTS if ids & set(a["affects_rules"])]


def amendments_for_plot(plot_area_sqm: float) -> list[dict]:
    out = []
    for a in AMENDMENTS:
        limit = a["applies_to"].get("max_plot_area_sqm")
        if limit is not None and plot_area_sqm <= limit:
            out.append(a)
    return out


def amendments_prompt_text() -> str:
    lines = []
    for a in AMENDMENTS:
        lines.append(
            f'<amendment id="{a["id"]}" date="{a["date"]}" clause="{a["clause"]}" status="{a["status"]}">\n'
            f'{a["summary_en"]}\nOnly verbatim words available: "{a["quoted_words"]}"\nSource: {a["source"]} - {a["source_url"]}\n</amendment>'
        )
    return "\n".join(lines)
