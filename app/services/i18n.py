"""Payslip labels in worker languages (offline, deterministic). Have native speakers review before launch."""
LANGS = ("en", "hi", "ta", "te")
KEYS = ["title", "month", "days_worked", "regular_hours", "overtime_hours", "rate",
        "basic_pay", "overtime_pay", "gross", "pf", "esi", "net"]
LABELS = {
    "en": ["Payslip", "Month", "Days worked", "Regular hours", "Overtime hours", "Rate per hour",
           "Basic pay", "Overtime pay", "Total earnings", "Provident fund (PF)", "Employee insurance (ESI)", "Take-home pay"],
    "hi": ["वेतन पर्ची", "महीना", "काम के दिन", "सामान्य घंटे", "ओवरटाइम घंटे", "प्रति घंटा दर",
           "मूल वेतन", "ओवरटाइम वेतन", "कुल कमाई", "भविष्य निधि (PF)", "कर्मचारी बीमा (ESI)", "हाथ में मिलने वाला वेतन"],
    "ta": ["சம்பளச் சீட்டு", "மாதம்", "வேலை செய்த நாட்கள்", "சாதாரண மணி நேரம்", "கூடுதல் நேர மணி", "ஒரு மணி நேர ஊதியம்",
           "அடிப்படை சம்பளம்", "கூடுதல் நேர சம்பளம்", "மொத்த வருமானம்", "வைப்பு நிதி (PF)", "ஊழியர் காப்பீடு (ESI)", "கையில் கிடைக்கும் சம்பளம்"],
    "te": ["జీతం స్లిప్", "నెల", "పనిచేసిన రోజులు", "సాధారణ గంటలు", "ఓవర్‌టైమ్ గంటలు", "గంటకు వేతనం",
           "ప్రాథమిక జీతం", "ఓవర్‌టైమ్ జీతం", "మొత్తం సంపాదన", "భవిష్య నిధి (PF)", "ఉద్యోగి బీమా (ESI)", "చేతికి వచ్చే జీతం"],
}
SUMMARY = {
    "en": "You worked {days} days and {ot} overtime hours. You take home ₹{net}.",
    "hi": "आपने {days} दिन काम किया और {ot} घंटे ओवरटाइम किया। आपको ₹{net} हाथ में मिलेंगे।",
    "ta": "நீங்கள் {days} நாட்கள் வேலை செய்தீர்கள், {ot} மணி கூடுதல் நேரம். உங்களுக்கு ₹{net} கிடைக்கும்.",
    "te": "మీరు {days} రోజులు పని చేశారు, {ot} గంటలు ఓవర్‌టైమ్. మీ చేతికి ₹{net} వస్తుంది.",
}
LANG_NAME = {"en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu"}


def norm(lang: str | None) -> str:
    return lang if lang in LANGS else "en"


def labels(lang: str) -> dict:
    return dict(zip(KEYS, LABELS[norm(lang)]))


def summary(lang: str, p: dict) -> str:
    return SUMMARY[norm(lang)].format(days=p["days_worked"], ot=p["overtime_hours"], net=f"{p['net']:,.0f}")
