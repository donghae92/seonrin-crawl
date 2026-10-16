from setuptools import setup, find_packages

setup(
    name="project",
    version="1.0",
    packages=find_packages(),
    package_data={"crawler": ["seeds.txt"]},  # seeds travel inside the deployed egg
    zip_safe=False,
    entry_points={"scrapy": ["settings = crawler.settings"]},
)
