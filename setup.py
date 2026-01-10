import setuptools

setuptools.setup(
    name="interactive_gym",
    version="0.1.0",
    description="A platform for running interactive experiments in the browser with standard simulation environments.",
    author="Chase McDonald",
    author_email="chasecmcdonald@gmail.com",
    packages=setuptools.find_packages(),
    install_requires=[
        "gymnasium==1.0.0",
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
    },
)
