from semantic_kernel.skill_definition import sk_function, sk_function_context_parameter
from news_agent import get_scraped_news
from summarizer import summarize_text_gemini


class NewsPlugin:
    @sk_function(
        description="Scrape and summarize news for a company",
        name="summarize_news"
    )
    @sk_function_context_parameter(name="company", description="Company name")
    def summarize_news(self, context) -> str:
        company = context["company"]
        articles = get_scraped_news(company)
        combined_text = "\n\n".join(a["content"] for a in articles)
        links = [a["url"] for a in articles]
        summary = summarize_text_gemini(combined_text)
        return {
            "summary": summary,
            "references": links
        }
