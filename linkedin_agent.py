from serpapi import GoogleSearch
from config import SERPAPI_API_KEY


class LinkedInProfileScraper:
    def __init__(self, api_key=SERPAPI_API_KEY):
        self.api_key = api_key

    def search_profiles(self, name, company, location="India"):
        query = f'site:linkedin.com/in "{name}" "{company}" "{location}"'
        search = GoogleSearch({
            "q": query,
            "api_key": self.api_key,
            "num": 10
        })
        results = search.get_dict()
        return [
            {
                "title": r.get("title"),
                "url": r.get("link"),
                "snippet": r.get("snippet")
            }
            for r in results.get("organic_results", [])[:3]
        ]
