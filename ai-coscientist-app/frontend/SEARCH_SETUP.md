# Search Engine Setup

The application ships its crawler files and metadata in the production build. After deployment:

1. Add `https://ai-co-scientist.com` as a Domain property in Google Search Console.
2. Complete the DNS verification step using the TXT value supplied by Google.
3. Submit `https://ai-co-scientist.com/sitemap.xml`.
4. Inspect `/` and each `/demos/:slug` URL and request indexing.
5. Add the domain in Bing Webmaster Tools, either by importing the Search Console property or completing Bing's verification.
6. Submit the same sitemap in Bing.

Do not submit `/runs` URLs. Vercel adds `X-Robots-Tag: noindex, nofollow` to those routes. The routes remain crawlable so search engines can read and honor that directive.
