``StaticScene``
===============

ok


``GymScene``
============
There are two ways to run MUG, depending on your use cases and requirements:

1. Server based. 

- This runs the environment on a server and allows for any number of human and AI players. At every step, the server will send the required information to all connected clients to update the environment client-side (e.g., the locations and any relevant data of updated objects).

2. Browser based. 

- This runs the environment in the browser using `Pyodide <https://pyodide.org/>`_. This approach has several limitations: the environment must be pure python and only a single human player is supported (although you may add any number of AI players). The benefit of this approach is that you circumvent (most) all of the issues associated with client server communication. Indeed, if participants do not have a stable internet connection (or are far from your sever), fast client-server communication can't be guaranteed and participant experience may degrade. In the browser-based approach, we also conduct model inference in the browser via ONNX.
