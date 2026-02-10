Getting Started
----------------

At a high level, a MUG experiment is defined by a set of scenes. 
Each scene defines what should be displayed to participants and what interactions can 
occur. 

There are two core types of scenes: ``StaticScene`` and ``GymScene``. The former just
displays static informaiton to clients and can also be used to collect some forms of data 
(e.g., text boxes, option buttons). The latter defines an interaction with a simulation 
environment and is where the core interactions occur. 

MUG utilizes a ``Stager``, which manages participants' progression through a sequence
of scenes. A ``Stager`` is initialized with a list of scenes and, when a participant joins, a stager
is initialized for that participant to track their progress through the scenes. 

A sequence of scenes must start with a ``StartScene`` and end with an ``EndScene``, both of which
are particular instances of a ``StaticScene``. At each ``StartScene`` and all intermediate ``StaticScene`` instances, 
a "Continue" button is displayed to allow participants to advance to the next scene. It is also possible to disable this button
until some condition is met (e.g., a participant must complete a particular action or selection before 
advancing).

A ``GymScenes`` takes in all parameters to configure interaction with a 
simulation environment (in ``PettingZoo`` parallel environment format).

The structure of a MUG experiment is as follows:

.. code-block:: python

    start_scene = (
        static_scene.StartScene()
        .scene(
            scene_id="my_start_scene",
        )
        .display(
            scene_header="Welcome to my MUG Experiment!",
            scene_body_filepath="This is an example body text for a start scene.",
        )
    )

    my_gym_scene = (
        gym_scene.GymScene(...)
        # Define all GymScene parameters here with the 
        # various GymScene configuration functions.
        # [...]
    )

    end_scene = static_scene.EndScene().display(
        scene_header="Thank you for playing!",
    )

    stager = stager.Stager(scenes=[start_scene, my_gym_scene, end_scene])


    if __name__ == "__main__":
        experiment_config = (
            experiment_config.ExperimentConfig()
            .experiment(stager=stager, experiment_id="my_experiment")
            .hosting(port=8000, host="0.0.0.0")
        )

        app.run(experiment_config)



.. include:: _getting_started/key_concepts.rst
