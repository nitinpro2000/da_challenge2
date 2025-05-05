from semantic_kernel.skill_definition import sk_function, sk_function_context_parameter
from linkedin_agent import LinkedInProfileScraper


class LinkedInPlugin:
    def __init__(self, api_key: str):
        self.scraper = LinkedInProfileScraper(api_key)

    @sk_function(
        description="Search LinkedIn profiles for a person at a company",
        name="search_profiles"
    )
    @sk_function_context_parameter(name="name", description="Name of the person")
    @sk_function_context_parameter(name="company", description="Company name")
    @sk_function_context_parameter(name="location", description="Location (optional)")
    def search_profiles(self, context) -> str:
        name = context["name"]
        company = context["company"]
        location = context.get("location", "India")
        results = self.scraper.search_profiles(name, company, location)
        return results
