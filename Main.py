from dotenv import load_dotenv
load_dotenv()

from input_processing import Reader, chunker
from extractor import Model, Extractor
from reportgenerator import reportMaker

def main():
    source = "https://www.usatoday.com/story/news/health/2025/09/15/covid-19-september-2025-cases-variants-symptoms-vaccines/86163707007/"  # or a URL

    # Step 1: Read and parse the source
    reader = Reader(source)
    parsed = reader.parse()

    # Step 2: Chunk the parsed content
    chunks = chunker(parsed)

    # Step 3: Extract and reduce
    extractor = Extractor(model=Model())
    result = extractor.run(chunks)

    # Step 4: Generate report
    report = reportMaker(model=Model())
    report_path = report.generate(result)

    print(f"Report saved to: {report_path}")

if __name__ == "__main__":
    main()