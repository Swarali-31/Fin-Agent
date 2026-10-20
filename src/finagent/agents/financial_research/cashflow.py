"""Answer direct saved-cashflow questions without a search or model dependency."""
import re

from finagent.schemas.common import AgentStatus
from finagent.schemas.research import ResearchRequest, ResearchResult

_SAVINGS_QUESTION = re.compile(
    r"(?:based on my (?:spending|expenses|income)(?: and (?:spending|expenses|income))?[, ]+)?"
    r"how much (?:can|could|do|might) i save(?: (?:each|per|a) month| monthly)?[?.!]*",
    re.IGNORECASE,
)


def cashflow_result(request: ResearchRequest) -> ResearchResult | None:
    """Only handle a narrow question whose answer is already in saved totals."""
    context = request.financial_context
    if not context or not context.summary or not _SAVINGS_QUESTION.fullmatch(request.question.strip()):
        return None
    language = request.response_language.lower()
    if language == "auto":
        language = "english"
    if language not in {"english", "bengali", "hindi"}:
        return None
    summary = context.summary
    received = f"{summary.monthly_income.amount:,.2f} {summary.currency}"
    spent = f"{summary.monthly_expenses.amount:,.2f} {summary.currency}"
    surplus = summary.available_surplus.amount
    remainder = f"{abs(surplus):,.2f} {summary.currency}"
    period = f"{summary.period_start} – {summary.period_end}"
    if language == "bengali":
        paragraphs = [
            f"আপনার সংরক্ষিত লেনদেন অনুযায়ী প্রতি মাসে গড়ে {received} টাকা এসেছে এবং {spent} খরচ হয়েছে। সময়কাল: {period}।",
            f"তাই একই আয় ও খরচ বজায় থাকলে মাসে প্রায় {remainder} সঞ্চয়ের জন্য অবশিষ্ট থাকতে পারে। হিসাবটি হলো: মাসিক গড় প্রাপ্ত অর্থ − মাসিক গড় খরচ।" if surplus > 0 else (
                f"প্রতি মাসে গড়ে {remainder} বেশি খরচ হয়েছে। তাই বর্তমান হিসাবে সঞ্চয়ের জন্য উদ্বৃত্ত নেই। আগে আয় ও খরচের এই ব্যবধান কমাতে হবে।" if surplus < 0 else "আপনার মাসিক গড় প্রাপ্ত অর্থ ও খরচ সমান। বর্তমান হিসাবে সঞ্চয়ের জন্য উদ্বৃত্ত নেই।"),
            "এটি অতীতের লেনদেনের হিসাব; আপনার ব্যাংকের বর্তমান ব্যালান্স বা নিশ্চিত ভবিষ্যৎ সঞ্চয় নয়। সংরক্ষিত তথ্যে কোনো খরচ বাদ থাকলে আসল অবশিষ্ট অর্থ কম হতে পারে।",
        ]
        extra = "নিয়মিত বিল, ঋণের কিস্তি ও অনিয়মিত খরচ মিলিয়ে দেখুন। তারপর অবশিষ্ট অর্থের মধ্যে একটি বাস্তবসম্মত সঞ্চয়ের লক্ষ্য ঠিক করুন এবং বাজেট পাতায় পরিকল্পনা তৈরি করুন।"
        demo = "ডেমো তথ্য: এই হিসাব নমুনা লেনদেনের ওপর ভিত্তি করে তৈরি।"
        refund = "প্রাপ্ত অর্থের মধ্যে ফেরত পাওয়া টাকাও রয়েছে; সেটিকে নিয়মিত আয় ধরে সঞ্চয়ের লক্ষ্য ঠিক করবেন না।"
    elif language == "hindi":
        paragraphs = [
            f"आपके सहेजे गए लेनदेन के अनुसार हर महीने औसतन {received} प्राप्त हुए और {spent} खर्च हुए। अवधि: {period}।",
            f"अगर यही आय और खर्च बने रहें, तो महीने में लगभग {remainder} बचत के लिए बच सकते हैं। गणना: मासिक औसत प्राप्त राशि − मासिक औसत खर्च।" if surplus > 0 else (
                f"हर महीने औसतन {remainder} अधिक खर्च हुए। मौजूदा आंकड़ों में बचत के लिए अधिशेष नहीं है; पहले आय और खर्च का अंतर कम करें।" if surplus < 0 else "मासिक प्राप्त राशि और खर्च बराबर हैं। मौजूदा आंकड़ों में बचत के लिए अधिशेष नहीं है।"),
            "यह पिछले लेनदेन का हिसाब है, आपके बैंक का मौजूदा बैलेंस या भविष्य की निश्चित बचत नहीं। कोई खर्च दर्ज नहीं हुआ है तो वास्तविक बची राशि कम हो सकती है।",
        ]
        extra = "नियमित बिल, ऋण की किस्तें और अनियमित खर्च जांचें। फिर बची राशि के भीतर व्यावहारिक बचत लक्ष्य तय करें और बजट पेज पर योजना बनाएं।"
        demo = "DEMO: यह हिसाब उदाहरण वाले लेनदेन पर आधारित है।"
        refund = "प्राप्त राशि में रिफंड भी शामिल हैं; बचत लक्ष्य तय करते समय उन्हें नियमित आय न मानें।"
    else:
        paragraphs = [
            f"Your saved transactions show average monthly money received of {received} and spending of {spent}, covering {period}.",
            f"If that pattern continues, about {remainder} per month could be available for saving. This is monthly money received minus monthly spending." if surplus > 0 else (
                f"You spent an average of {remainder} more than you received each month. There is no recorded surplus available for saving at this spending level; close that gap first." if surplus < 0 else "Your average monthly receipts and spending are equal, leaving no recorded surplus for saving."),
            "This is a calculation from recorded transactions, not your current bank balance or a guarantee of future savings. Missing bills or other unrecorded costs could reduce what is actually available.",
        ]
        extra = "Check regular bills, debt repayments and occasional costs before setting a target. Then choose a realistic amount within your surplus and use Budget Planning to build or update the plan. You do not need to save the entire surplus if some of it must cover irregular expenses."
        demo = "DEMO: these figures use sample transactions rather than personal financial records."
        refund = "Money received includes refunds. Do not assume those refunds are recurring earnings when choosing a savings target."
    if request.response_detail == "detailed":
        paragraphs.append(extra)
    if summary.refund_total and summary.refund_total.amount > 0:
        paragraphs.append(refund)
    if context.is_sample:
        paragraphs.insert(0, demo)
    return ResearchResult(status=AgentStatus.success, question=request.question,
        calculated_answer="\n\n".join(paragraphs), financial_context=context)
