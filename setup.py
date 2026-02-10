import setuptools

setuptools.setup(
    name="multi_user_gymnasium",
    version="0.1.1",
    description="A platform for running interactive experiments in the browser with standard simulation environments.",
    author="Chase McDonald",
    author_email="chasecmcdonald@gmail.com",
    packages=setuptools.find_packages(),
    install_requires=[
        "numpy",
    ],
    extras_require={
        "server": [
            "eventlet",
            "flask",
            "flask-socketio",
            "msgpack",
            "pandas",
            "flatten_dict",
        ],
        "test": [
            "pytest>=8.0",
            "playwright>=1.49",
            "pytest-playwright>=0.6",
            "pytest-timeout>=2.3",
        ],
    },
)
