from __future__ import annotations

from typing import Any

from flask_socketio import SocketIO

from interactive_gym.scenes import scene
from interactive_gym.scenes.utils import NotProvided


class StaticScene(scene.Scene):
    """
    A class representing a static scene in the Interactive Gym.

    StaticScene is used to display static content to participants, such as
    instructions, information, or data collection forms. It extends the base
    Scene class and provides methods to set the content of the scene.

    The most critical component of this class is the `scene_body` attribute,
    which should contain plaintext or HTML (and Javascript) to display
    to the user.

    If you would like to put restrictions on the user being able to advance the
    scene, you can add Javascript to the `scene_body` attribute that conditionally
    disables/enables the #advanceButton element (which will be globally accessible).

    If you are creating elements that require data collection, add the element IDs to
    the StaticScene.element_ids list. These IDs will be used to retrieve the data from the
    client and send it back to the server to be saved. This process happens automatically.
    """

    def __init__(self):
        super().__init__()
        # The main header text for the scene
        self.scene_header: str = ""
        # A subheader text for the scene
        self.scene_subheader: str = ""
        # The main content body of the scene, which can be HTML
        self.scene_body: str = ""  # Fixed typo: 'self_body' to 'scene_body'

    def display(
        self,
        scene_header: str = NotProvided,
        scene_subheader: str = NotProvided,
        scene_body: str = NotProvided,
        scene_body_filepath: str = NotProvided,
    ) -> StaticScene:
        """Sets the content to be displayed in the static scene.

        This method allows you to set the header, subheader, and body content of the static scene.
        You can provide the body content directly as a string or specify a filepath to load the content from.

        :param scene_header: The main header text for the scene, defaults to NotProvided
        :type scene_header: str, optional
        :param scene_subheader: A subheader text for the scene, defaults to NotProvided
        :type scene_subheader: str, optional
        :param scene_body: The main content body of the scene as a string (can be HTML), defaults to NotProvided
        :type scene_body: str, optional
        :param scene_body_filepath: Path to a file containing the scene body content, defaults to NotProvided
        :type scene_body_filepath: str, optional
        :return: The current StaticScene instance for method chaining
        :rtype: StaticScene

        :raises AssertionError: If both scene_body and scene_body_filepath are provided
        """
        if scene_body_filepath is not NotProvided:
            assert (
                scene_body is NotProvided
            ), "Cannot set both filepath and html_body."

            with open(scene_body_filepath, "r", encoding="utf-8") as f:
                self.scene_body = f.read()

        if scene_body is not NotProvided:
            assert (
                scene_body_filepath is NotProvided
            ), "Cannot set both filepath and html_body."
            self.scene_body = scene_body

        if scene_header is not NotProvided:
            self.scene_header = scene_header

        if scene_subheader is not NotProvided:
            self.scene_subheader = scene_subheader

        return self


class StartScene(StaticScene):
    """
    The StartScene is a special Scene that marks the beginning of the Stager sequence.
    """

    def __init__(self):
        super().__init__()
        self.should_export_metadata = True


class EndScene(StaticScene):
    """
    The EndScene is a special Scene that marks the end of the Stager sequence.

    If a redirect URL is provided, a button will appear to participants that will redirect them when
    clicked. Optionally, their subject_id can be appended to the URL (useful in cases where you
    are forwarding them to personalized surveys, etc.)
    """

    def __init__(self):
        super().__init__()
        self.url: str | None = None
        self.append_subject_id: bool = False

    def redirect(
        self, url: str = NotProvided, append_subject_id: bool = NotProvided
    ) -> EndScene:
        """Configure the redirect URL for the EndScene.

        :param url: The URL to redirect to after the EndScene, defaults to NotProvided
        :type url: str, optional
        :param append_subject_id: Whether to append the subject_id to the redirect URL, defaults to NotProvided
        :type append_subject_id: bool, optional
        :return: The current EndScene instance for method chaining
        :rtype: EndScene
        """
        if url is not NotProvided:
            self.url = url

        if append_subject_id is not NotProvided:
            self.append_subject_id = append_subject_id

        return self


class CompletionCodeScene(EndScene):
    """A special EndScene that generates and displays a unique completion code.

    This scene is typically used at the end of an experiment to provide participants
    with a unique code that they can use to verify their participation or claim compensation.
    """

    def __init__(self):
        super().__init__()
        self.completion_code = None
        self.should_export_metadata = True

    def build(self):
        self.scene_body, self.completion_code = (
            self._create_html_completion_code()
        )
        return super().build()

    def _create_html_completion_code(self) -> str:
        """Create HTML content for displaying a completion code.

        This method generates a unique completion code using UUIDs and formats it as HTML.
        It also includes instructions for participants to copy and submit the code.

        :return: A tuple containing the HTML content and the completion code
        :rtype: tuple[str, str]
        """
        import uuid

        completion_code = str(uuid.uuid4())
        html = f"""
        <p>Your completion code is:</p>
        <h2 style="font-family: monospace; background-color: #f0f0f0; padding: 10px; border-radius: 5px;">{completion_code}</h2>
        <p>Please copy this code and submit it to validate your participation.</p>
        """
        return html, completion_code

    @property
    def scene_metadata(self) -> dict:
        """
        Return the metadata for the current scene that will be passed through the Flask app.
        """
        metadata = super().scene_metadata
        metadata["completion_code"] = self.completion_code
        return metadata


class OptionBoxes(StaticScene):
    """A StaticScene that presents a set of clickable option boxes to the user.

    This scene displays a horizontal line of colored boxes, each representing an option.
    Users can click on a box to select it, which enables the advance button.
    """

    def __init__(
        self, scene_id: str, experiment_config: dict, options: list[str]
    ):
        super().__init__(scene_id, experiment_config)

        self.scene_body = self._create_html_option_boxes(options)

    def _create_html_option_boxes(self, options: list[str]) -> str:
        """
        Given a list of N options, creates HTML code to display a horizontal line of N boxes,
        each with a unique color. Each box is labeled by a string in the options list.
        When a user clicks a box, it becomes highlighted.
        The advance button is only enabled when a box is clicked.
        """
        colors = [
            "#FF6F61",
            "#6B5B95",
            "#88B04B",
            "#F7CAC9",
            "#92A8D1",
            "#955251",
            "#B565A7",
            "#009B77",
        ]  # Example colors
        html = '<div id="option-boxes-container" style="display: flex; justify-content: space-around; gap: 10px;">\n'

        for i, option in enumerate(options):
            color = colors[
                i % len(colors)
            ]  # Cycle through colors if there are more options than colors
            html += f"""
            <div id="option-{i}" class="option-box" style="
                background-color: {color};
                padding: 20px;
                cursor: pointer;
                border-radius: 10px;
                border: 2px solid transparent;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                text-align: center;
                transition: transform 0.2s ease, box-shadow 0.2s ease;">
                <span style="font-size: 16px; color: white;">{option}</span>
            </div>
            """

        html += "</div>\n"
        html += """
        <script>
        $("#advanceButton").attr("disabled", true);
        $("#advanceButton").show();

        document.querySelectorAll('.option-box').forEach(function(box) {
            box.addEventListener('click', function() {
                // Reset all boxes
                document.querySelectorAll('.option-box').forEach(function(b) {
                    b.style.border = '2px solid transparent';
                    b.style.transform = 'scale(1)';
                    b.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)';
                });

                // Highlight the clicked box
                box.style.border = '2px solid black';
                box.style.transform = 'scale(1.05)';
                box.style.boxShadow = '0 8px 16px rgba(0, 0, 0, 0.2)';

                // Enable the advance button
                document.getElementById('advanceButton').disabled = false;
            });
        });

        </script>
        """

        return html


class TextBox(StaticScene):
    """A StaticScene that displays a text box for user input.

    This scene includes a text box where users can enter text. The advance button
    is only enabled when text is entered.
    """

    def __init__(
        self,
        text_box_header: str,
        required: bool = True,
    ):
        super().__init__()
        self.required = required
        self.scene_body = self._create_html_text_box(text_box_header)
        self.element_ids = ["user-input"]

    def display(
        self,
        text_box_header: str = NotProvided,
        **kwargs,
    ) -> StaticScene:
        """Display the TextBox scene with the given header.

        This method configures the display of the TextBox scene. If a new text_box_header
        is provided, it updates the scene's body with a new text box using that header.

        :param text_box_header: The header text to display above the text box. If not provided,
                                the existing header will be used, defaults to NotProvided
        :type text_box_header: str, optional
        :return: The current StaticScene instance
        :rtype: StaticScene
        """
        super().display(**kwargs)

        if text_box_header is not NotProvided:
            self.scene_body = self._create_html_text_box(text_box_header)

        return self

    def _create_html_text_box(self, text_box_header: str) -> str:
        """
        Creates HTML code to display a text box with a header.
        The advance button is only enabled when text is entered.
        """
        html = f"""
        <div style="margin-top: 20px; text-align: center;">
            <h3>{text_box_header}</h3>
            <textarea id="user-input" rows="4" cols="50" style="width: 100%; max-width: 500px;"></textarea>
        </div>
        """

        if self.required:
            html += """
            <script>
            $(document).ready(function() {
                $("#advanceButton").attr("disabled", true);
                $("#advanceButton").show();
                $("#user-input").on("input", function() {
                    if ($(this).val().trim().length > 0) {
                        $("#advanceButton").attr("disabled", false);
                    } else {
                        $("#advanceButton").attr("disabled", true);
                    }
                });
            });
            </script>
            """

        return html


class OptionBoxesWithTextBox(StaticScene):
    """A StaticScene subclass that displays option boxes and a text box.

    This class creates a scene with multiple clickable option boxes and a text input box.
    It allows users to select an option and provide additional text input.

    :param StaticScene: The parent class for static scenes in the Interactive Gym.
    :type StaticScene: StaticScene
    """

    def __init__(
        self,
        scene_id: str,
        experiment_config: dict,
        options: list[str],
        text_box_header: str,  # TODO(chase): Move this to .display()
    ):
        super().__init__(scene_id, experiment_config)

        self.scene_body = self._create_html_option_boxes(
            options, text_box_header
        )

    def _create_html_option_boxes(
        self, options: list[str], text_box_header: str
    ) -> str:
        """
        Given a list of N options, creates HTML code to display a horizontal line of N boxes,
        each with a unique color. Each box is labeled by a string in the options list.
        When a user clicks a box, it becomes highlighted.
        The advance button is only enabled when a box is clicked.
        """
        colors = [
            "#FF6F61",
            "#6B5B95",
            "#88B04B",
            "#F7CAC9",
            "#92A8D1",
            "#955251",
            "#B565A7",
            "#009B77",
        ]  # Example colors
        html = '<div id="option-boxes-container" style="display: flex; justify-content: space-around; gap: 10px;">\n'

        for i, option in enumerate(options):
            color = colors[
                i % len(colors)
            ]  # Cycle through colors if there are more options than colors
            html += f"""
            <div id="option-{i}" class="option-box" style="
                background-color: {color};
                padding: 20px;
                cursor: pointer;
                border-radius: 10px;
                border: 2px solid transparent;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                text-align: center;
                transition: transform 0.2s ease, box-shadow 0.2s ease;">
                <span style="font-size: 16px; color: white;">{option}</span>
            </div>
            """

        html += "</div>\n"
        html += "</div>\n"

        # Add text box
        html += f"""
        <div style="margin-top: 20px; text-align: center;">
            <h3>{text_box_header}</h3>
            <textarea id="user-input" rows="4" cols="50" style="width: 100%; max-width: 500px;"></textarea>
        </div>
        """

        html += """
        <script>
        $("#advanceButton").attr("disabled", true);
        $("#advanceButton").show();

        function checkInputs() {
            var boxSelected = document.querySelector('.option-box[style*="border: 2px solid black"]') !== null;
            var textEntered = document.getElementById('user-input').value.trim() !== '';
            document.getElementById('advanceButton').disabled = !(boxSelected && textEntered);
        }

        document.querySelectorAll('.option-box').forEach(function(box) {
            box.addEventListener('click', function() {
                // Reset all boxes
                document.querySelectorAll('.option-box').forEach(function(b) {
                    b.style.border = '2px solid transparent';
                    b.style.transform = 'scale(1)';
                    b.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)';
                });

                // Highlight the clicked box
                box.style.border = '2px solid black';
                box.style.transform = 'scale(1.05)';
                box.style.boxShadow = '0 8px 16px rgba(0, 0, 0, 0.2)';

                // Enable the advance button
                document.getElementById('advanceButton').disabled = false;

                checkInputs();
            });
        });

        document.getElementById('user-input').addEventListener('input', checkInputs);
        </script>
        """

        return html


class OptionBoxesWithScalesAndTextBox(StaticScene):
    """A StaticScene subclass that displays option boxes with scales and a text box.

    This class creates a static scene with multiple interactive elements:
    - Option boxes that can be selected
    - Likert scales for rating different aspects
    - A text box for additional input

    """

    def __init__(
        self,
        options: list[str],
        text_box_header: str,  # TODO(chase): Move this to .display()
        pre_scale_header: str,
        scale_questions: list[str],
        option_box_header: str,
        scale_size: int = 21,
        scale_labels: list[str] = [
            "Strongly Disagree",
            "Disagree",
            "Neutral",
            "Agree",
            "Strongly Agree",
        ],
    ):
        super().__init__()
        self.pre_scale_header = pre_scale_header
        self.scale_size = scale_size
        self.scale_questions = scale_questions
        self.scale_labels = scale_labels
        self.option_box_header = option_box_header
        self.scene_body = self._create_html(options, text_box_header)
        self.element_ids = self.get_data_element_ids()

    def _create_html(self, options: list[str], text_box_header: str) -> str:
        """
        Given a list of N options, creates HTML code to display a horizontal line of N boxes,
        each with a unique color. Each box is labeled by a string in the options list.
        When a user clicks a box, it becomes highlighted.
        The advance button is only enabled when a box is clicked, all scales are interacted with, and text is entered.
        """
        colors = [
            "#FF6F61",
            "#6B5B95",
            "#88B04B",
            "#F7CAC9",
            "#92A8D1",
            "#955251",
            "#B565A7",
            "#009B77",
        ]  # Example colors
        html = f'<p style="text-align: center;">{self.option_box_header} <span style="color: red;">*</span></p>\n'
        html += '<div id="option-boxes-container" style="display: flex; justify-content: space-around; gap: 10px;">\n'

        for i, option in enumerate(options):
            color = colors[
                i % len(colors)
            ]  # Cycle through colors if there are more options than colors
            html += f"""
            <div id="option-{i}" class="option-box" data-option="{option}" style="
                background-color: {color};
                padding: 20px;
                cursor: pointer;
                border-radius: 10px;
                border: 2px solid transparent;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                text-align: center;
                transition: transform 0.2s ease, box-shadow 0.2s ease;">
                <span style="font-size: 16px; color: white;">{option}</span>
            </div>
            """

        html += "</div>\n"
        html += '<input type="hidden" id="selected-option-box" name="selected-option-box" value="">\n'

        # Add more space between option boxes and pre-scale header
        html += '<div style="margin-top: 50px;"></div>\n'

        # Add pre-scale header
        html += f'<p style="text-align: center;">{self.pre_scale_header}</p>\n'

        # Add slider scales
        html += (
            '<div id="scale-questions-container" style="margin-top: 20px;">\n'
        )
        for i, question in enumerate(self.scale_questions):
            html += f"""
            <div class="scale-question" style="margin-bottom: 15px; text-align: center;">
                <div style="border: 1px solid #ccc; padding: 10px; display: inline-block; margin: 0 auto; width: 80%;">
                    <p style="margin: 0 0 10px 0;">{question} <span style="color: red;">*</span></p>
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <span style="flex: 1; text-align: left; font-size: 12px;">{self.scale_labels[0]}</span>
                        <span style="flex: 1; text-align: center; font-size: 12px;">{self.scale_labels[len(self.scale_labels)//2]}</span>
                        <span style="flex: 1; text-align: right; font-size: 12px;">{self.scale_labels[-1]}</span>
                    </div>
                    <div style="display: flex; align-items: center; justify-content: center;">
                        <input type="range" id="scale-{i}" class="scale-input" min="0" max="{self.scale_size - 1}" value="{(self.scale_size - 1) // 2}" style="margin: 10px 0; -webkit-appearance: none; appearance: none; width: 100%; height: 2px; background: #d3d3d3; outline: none; opacity: 0.7; transition: opacity .2s;">
                    </div>
                </div>
            </div>
            <style>
                #scale-{i}::-webkit-slider-thumb {{
                    -webkit-appearance: none;
                    appearance: none;
                    width: 20px;
                    height: 20px;
                    border-radius: 50%;
                    background: #d3d3d3;
                    cursor: pointer;
                    transition: background 0.3s ease;
                }}
                #scale-{i}::-moz-range-thumb {{
                    width: 20px;
                    height: 20px;
                    border-radius: 50%;
                    background: #d3d3d3;
                    cursor: pointer;
                    transition: background 0.3s ease;
                }}
                #scale-{i}.interacted::-webkit-slider-thumb {{
                    background: #4CAF50;
                }}
                #scale-{i}.interacted::-moz-range-thumb {{
                    background: #4CAF50;
                }}
            </style>
            """
        html += "</div>\n"

        # Add text box
        html += f"""
        <div style="margin-top: 20px; text-align: center;">
            <p>{text_box_header} <span style="color: red;">*</span></p>
            <textarea id="user-input" rows="4" cols="50" style="width: 100%; max-width: 500px;"></textarea>
        </div>
        """

        html += """
        <script>
        $("#advanceButton").attr("disabled", true);
        $("#advanceButton").show();

        function checkInputs() {
            var boxSelected = document.querySelector('.option-box[style*="border: 2px solid black"]') !== null;
            var textEntered = document.getElementById('user-input').value.trim() !== '';
            var allScalesInteracted = Array.from(document.querySelectorAll('.scale-input')).every(scale => scale.classList.contains('interacted'));
            document.getElementById('advanceButton').disabled = !(boxSelected && textEntered && allScalesInteracted);
        }

        document.querySelectorAll('.option-box').forEach(function(box) {
            box.addEventListener('click', function() {
                // Reset all boxes
                document.querySelectorAll('.option-box').forEach(function(b) {
                    b.style.border = '2px solid transparent';
                    b.style.transform = 'scale(1)';
                    b.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)';
                });

                // Highlight the clicked box
                box.style.border = '2px solid black';
                box.style.transform = 'scale(1.05)';
                box.style.boxShadow = '0 8px 16px rgba(0, 0, 0, 0.2)';

                // Set the selected option
                document.getElementById('selected-option-box').value = box.getAttribute('data-option');

                checkInputs();
            });
        });

        document.getElementById('user-input').addEventListener('input', checkInputs);
        document.querySelectorAll('.scale-input').forEach(function(scale) {
            scale.addEventListener('input', function() {
                if (!this.classList.contains('interacted')) {
                    this.classList.add('interacted');
                }
                checkInputs();
            });
        });
        </script>
        """

        return html

    def get_data_element_ids(self) -> list[str]:
        """
        Identifies and returns a list of element IDs that should be retrieved to store user input data.

        Returns:
            list[str]: A list of element IDs corresponding to user input data.
        """
        element_ids = []

        # Add the ID for the selected option box
        element_ids.append("selected-option-box")

        # Add the ID for the text input
        element_ids.append("user-input")

        # Add IDs for all range inputs (scales)
        for i in range(len(self.scale_questions)):
            element_ids.append(f"scale-{i}")

        return element_ids


class ScalesAndTextBox(StaticScene):
    """A StaticScene subclass that displays option boxes with scales and a text box.

    This class creates a static scene with multiple interactive elements:
    - Option boxes that can be selected
    - Likert scales for rating different aspects
    - A text box for additional input

    """

    def __init__(
        self,
        text_box_header: str,  # TODO(chase): Move this to .display()
        pre_scale_header: str,
        scale_questions: list[str],
        scale_size: int = 21,
        scale_labels: list[str] = [
            "Strongly Disagree",
            "Disagree",
            "Neutral",
            "Agree",
            "Strongly Agree",
        ],
    ):
        super().__init__()
        self.pre_scale_header = pre_scale_header
        self.scale_size = scale_size
        self.scale_questions = scale_questions

        if isinstance(scale_labels[0], list):
            self.scale_labels = scale_labels
        elif isinstance(scale_labels[0], str):
            self.scale_labels = [scale_labels] * len(scale_questions)
        else:
            raise ValueError(
                "scale_labels must be a list of strings or a list of lists of strings"
            )

        self.scene_body = self._create_html(text_box_header)
        self.element_ids = self.get_data_element_ids()

    def _create_html(self, text_box_header: str) -> str:
        """
        Given a list of N options, creates HTML code to display a horizontal line of N boxes,
        each with a unique color. Each box is labeled by a string in the options list.
        When a user clicks a box, it becomes highlighted.
        The advance button is only enabled when a box is clicked, all scales are interacted with, and text is entered.
        """
        html = ""

        # Add pre-scale header
        html += f'<p style="text-align: center;">{self.pre_scale_header}</p>\n'

        # Add slider scales
        html += (
            '<div id="scale-questions-container" style="margin-top: 20px;">\n'
        )
        for i, question in enumerate(self.scale_questions):
            # Build label spans for all labels, evenly distributed
            labels = self.scale_labels[i]
            num_labels = len(labels)
            label_spans = ""
            for j, label in enumerate(labels):
                if num_labels == 1:
                    text_align = "center"
                elif j == 0:
                    text_align = "left"
                elif j == num_labels - 1:
                    text_align = "right"
                else:
                    text_align = "center"
                label_spans += f'<span style="text-align: {text_align}; font-size: 12px;">{label}</span>\n'

            html += f"""
            <div class="scale-question" style="margin-bottom: 15px; text-align: center;">
                <div style="border: 1px solid #ccc; padding: 10px; display: inline-block; margin: 0 auto; width: 80%;">
                    <p style="margin: 0 0 10px 0;">{question} <span style="color: red;">*</span></p>
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        {label_spans}
                    </div>
                    <div style="display: flex; align-items: center; justify-content: center;">
                        <input type="range" id="scale-{i}" class="scale-input" min="0" max="{self.scale_size - 1}" value="{(self.scale_size - 1) // 2}" style="margin: 10px 0; -webkit-appearance: none; appearance: none; width: 100%; height: 2px; background: #d3d3d3; outline: none; opacity: 0.7; transition: opacity .2s;">
                    </div>
                </div>
            </div>
            <style>
                #scale-{i}::-webkit-slider-thumb {{
                    -webkit-appearance: none;
                    appearance: none;
                    width: 20px;
                    height: 20px;
                    border-radius: 50%;
                    background: #d3d3d3;
                    cursor: pointer;
                    transition: background 0.3s ease;
                }}
                #scale-{i}::-moz-range-thumb {{
                    width: 20px;
                    height: 20px;
                    border-radius: 50%;
                    background: #d3d3d3;
                    cursor: pointer;
                    transition: background 0.3s ease;
                }}
                #scale-{i}.interacted::-webkit-slider-thumb {{
                    background: #4CAF50;
                }}
                #scale-{i}.interacted::-moz-range-thumb {{
                    background: #4CAF50;
                }}
            </style>
            """
        html += "</div>\n"

        # Add text box
        html += f"""
        <div style="margin-top: 20px; text-align: center;">
            <p>{text_box_header} <span style="color: red;">*</span></p>
            <textarea id="user-input" rows="4" cols="50" style="width: 100%; max-width: 500px;"></textarea>
        </div>
        """

        html += """
        <script>
        $("#advanceButton").attr("disabled", true);
        $("#advanceButton").show();

        function checkInputs() {
            var textEntered = document.getElementById('user-input').value.trim() !== '';
            var allScalesInteracted = Array.from(document.querySelectorAll('.scale-input')).every(scale => scale.classList.contains('interacted'));
            document.getElementById('advanceButton').disabled = !(textEntered && allScalesInteracted);
        }

        document.getElementById('user-input').addEventListener('input', checkInputs);
        document.querySelectorAll('.scale-input').forEach(function(scale) {
            scale.addEventListener('mousedown', function() {
                if (!this.classList.contains('interacted')) {
                    this.classList.add('interacted');
                    checkInputs();
                }
            });
            scale.addEventListener('input', function() {
                if (!this.classList.contains('interacted')) {
                    this.classList.add('interacted');
                }
                checkInputs();
            });
        });
        </script>
        """

        return html

    def get_data_element_ids(self) -> list[str]:
        """
        Identifies and returns a list of element IDs that should be retrieved to store user input data.

        Returns:
            list[str]: A list of element IDs corresponding to user input data.
        """
        element_ids = []

        # Add the ID for the text input
        element_ids.append("user-input")

        # Add IDs for all range inputs (scales)
        for i in range(len(self.scale_questions)):
            element_ids.append(f"scale-{i}")

        return element_ids


class MultipleChoice(StaticScene):
    """A StaticScene subclass that displays multiple choice questions.

    This class creates a static scene with multiple choice questions that can be either
    radio buttons (single select) or checkboxes (multi select).
    """

    def __init__(
        self,
        pre_questions_header: str,
        questions: list[str],
        choices: list[list[str]],
        multi_select: bool | list[bool] = False,
        images: list[str | None] | None = None,
    ):
        super().__init__()
        self.pre_questions_header = pre_questions_header
        self.questions = questions
        self.images = images or [None] * len(questions)

        if isinstance(choices[0], list):
            self.choices = choices
        elif isinstance(choices[0], str):
            self.choices = [choices] * len(questions)
        else:
            raise ValueError(
                "choices must be a list of strings or a list of lists of strings"
            )

        if isinstance(multi_select, list):
            self.multi_select = multi_select
        else:
            self.multi_select = [multi_select] * len(questions)

        assert len(self.questions) == len(
            self.choices
        ), "Number of questions must match number of choice sets"
        assert len(self.questions) == len(
            self.multi_select
        ), "Number of questions must match number of multi_select flags"
        assert len(self.questions) == len(
            self.images
        ), "Number of questions must match number of images"

        self.scene_body = self._create_html()
        self.element_ids = self.get_data_element_ids()

    def _create_html(self) -> str:
        """
        Creates HTML code to display multiple choice questions.
        Questions can be either single-select (radio) or multi-select (checkbox).
        The advance button is only enabled when all questions are answered.
        """
        html = (
            f'<p style="text-align: center;">{self.pre_questions_header}</p>\n'
        )

        # Add multiple choice questions
        html += '<div id="mc-questions-container" style="margin-top: 20px;">\n'
        for i, (question, choices, is_multi, image) in enumerate(
            zip(self.questions, self.choices, self.multi_select, self.images)
        ):
            input_type = "checkbox" if is_multi else "radio"
            html += f"""
            <div class="mc-question" style="margin-bottom: 25px; text-align: left;">
                <div style="border: 1px solid #ccc; padding: 15px; margin: 0 auto; width: 80%; border-radius: 5px;">
                    <p style="margin: 0 0 10px 0; font-weight: bold;">{question} <span style="color: red;">*</span></p>
            """

            # Add image if provided
            if image:
                html += f"""
                    <div style="text-align: center; margin: 15px 0;">
                        <img src="{image}" alt="Question {i+1} image" style="max-width: 100%; height: auto;">
                    </div>
                """

            html += f"""
                    <div class="input-group" id="mc-{i}-group" style="display: flex; flex-direction: column; gap: 8px;">
            """

            for j, choice in enumerate(choices):
                html += f"""
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                            <input type="{input_type}" name="mc-{i}" id="mc-{i}-{j}" value="{choice}" class="mc-input"
                                style="cursor: pointer; width: 16px; height: 16px;">
                            <span style="flex: 1;">{choice}</span>
                        </label>
                """

            html += """
                    </div>
                </div>
            </div>
            """
        html += "</div>\n"

        html += """
        <script>
        $("#advanceButton").attr("disabled", true);
        $("#advanceButton").show();

        function updateFormData() {
            $('.input-group').each(function(index) {
                var groupName = 'mc-' + index;
                var $inputs = $(this).find('input');
                var selectedIndices = [];
                
                $inputs.each(function(optionIndex) {
                    if (this.checked) {
                        selectedIndices.push(optionIndex);
                    }
                });
                
                // Create or update a hidden input to store the selected indices
                var hiddenInput = document.getElementById(groupName);
                if (!hiddenInput) {
                    hiddenInput = document.createElement('input');
                    hiddenInput.type = 'hidden';
                    hiddenInput.id = groupName;
                    document.body.appendChild(hiddenInput);
                }
                // Format as a proper list [0,1,2] instead of a string "0,1,2"
                hiddenInput.value = '[' + selectedIndices.join(',') + ']';
            });
        }

        function checkInputs() {
            var allQuestionsAnswered = Array.from(document.querySelectorAll('.input-group')).every(group => {
                var inputs = group.querySelectorAll('input');
                var isCheckbox = inputs[0].type === 'checkbox';
                if (isCheckbox) {
                    return Array.from(inputs).some(input => input.checked);
                } else {
                    return Array.from(inputs).some(input => input.checked);
                }
            });
            document.getElementById('advanceButton').disabled = !allQuestionsAnswered;
            updateFormData();  // Update the form data whenever inputs change
        }

        document.querySelectorAll('.mc-input').forEach(function(input) {
            input.addEventListener('change', checkInputs);
        });
        </script>
        """

        return html

    def get_data_element_ids(self) -> list[str]:
        """
        Identifies and returns a list of element IDs that should be retrieved to store user input data.

        For multi-select questions, all selected values will be returned as a comma-separated string.
        For single-select questions, only the selected value will be returned.

        Returns:
            list[str]: A list of element IDs corresponding to user input data.
        """
        # Add names (not IDs) for all question groups
        return [f"mc-{i}" for i in range(len(self.questions))]
