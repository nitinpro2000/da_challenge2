import json
from semantic_kernel.kernel import Kernel
from plugins.linkedin_plugin import LinkedInPlugin
from plugins.news_plugin import NewsPlugin
from config import SERPAPI_API_KEY


def main():
    kernel = Kernel()
    
    # Register plugins
    kernel.import_skill(LinkedInPlugin(SERPAPI_API_KEY), "LinkedInPlugin")
    kernel.import_skill(NewsPlugin(), "NewsPlugin")

    # Define context
    context = kernel.create_new_context()
    context["name"] = "Delvin Saji"
    context["company"] = "Tredence"
    context["location"] = "India"

    # Call LinkedIn Agent
    linkedin_output = kernel.skills.get_function("LinkedInPlugin", "search_profiles")(context)
    
    # Call News Summarizer Agent
    news_output = kernel.skills.get_function("NewsPlugin", "summarize_news")(context)

    result = {
        "summary": news_output["summary"],
        "references": news_output["references"],
        "linkedin_profiles": linkedin_output
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
