from slime_volleyball import slimevolley_boost_env
from slime_volleyball.core import constants as slimevb_constants
import math
from interactive_gym.configurations.object_contexts import Line, Circle, Polygon

Y_OFFSET = 0.018

def to_x(x):
    return x / slimevb_constants.REF_W + 0.5


def to_y(y):
    return 1 - y / slimevb_constants.REF_W


def slime_volleyball_env_to_rendering(
    env: slimevolley_boost_env.SlimeVolleyBoostEnv,
) -> list:
    render_objects = []

    # static objects only rendered on the first frame
    if env.t == 0:
        fence = Line(
            uuid="fence",
            color="#000000",
            points=[
                (
                    to_x(env.game.fence.x),
                    to_y(env.game.fence.y + env.game.fence.h / 2),
                ),
                (
                    to_x(env.game.fence.x),
                    to_y(env.game.fence.y - env.game.fence.h / 2),
                ),
            ],
            width=env.game.fence.w * 600 / slimevb_constants.REF_W,
            permanent=True,
        )
        render_objects.append(fence)

        fence_stub = Circle(
            uuid="fence_stub",
            color="#000000",
            x=to_x(env.game.fence_stub.x),
            y=to_y(env.game.fence_stub.y),
            radius=env.game.fence_stub.r * 600 / slimevb_constants.REF_W,
            permanent=True,
        )
        render_objects.append(fence_stub)

        ground = Line(
            uuid="ground",
            color="#747275",
            points=[
                (
                    0,
                    1
                    - env.game.ground.y / slimevb_constants.REF_W
                    - slimevb_constants.REF_U / slimevb_constants.REF_W / 2,
                ),
                (
                    1,
                    1
                    - env.game.ground.y / slimevb_constants.REF_W
                    - slimevb_constants.REF_U / slimevb_constants.REF_W / 2,
                ),
            ],
            fill_below=True,
            width=env.game.ground.w / slimevb_constants.REF_W,
            depth=-1,
            permanent=True,
        )
        render_objects.append(ground)

    left_is_boosting = env.game.agent_left.powered_up_timer > 0
    render_objects += generate_slime_agent_objects(
        "agent_left",
        x=env.game.agent_left.x,
        y=env.game.agent_left.y,
        dir=env.game.agent_left.dir,
        radius=env.game.agent_left.r,
        is_boosting=left_is_boosting,
        color="#FF0000",
        env=env,
    )

    right_is_boosting = env.game.agent_right.powered_up_timer > 0
    render_objects += generate_slime_agent_objects(
        "agent_right",
        x=env.game.agent_right.x,
        y=env.game.agent_right.y,
        dir=env.game.agent_right.dir,
        radius=env.game.agent_right.r,
        is_boosting=right_is_boosting,
        color="#0000FF",
        env=env,
    )

    terminateds, _ = env.get_terminateds_truncateds()
    ball = Circle(
        uuid="ball",
        color="#000000" if not terminateds["__all__"] else "#AAFF00",
        x=env.game.ball.x / slimevb_constants.REF_W + 0.5,
        y=1 - env.game.ball.y / slimevb_constants.REF_W,
        radius=env.game.ball.r * 600 / slimevb_constants.REF_W,
    )
    render_objects.append(ball)

    return [obj.as_dict() for obj in render_objects]


def generate_slime_agent_objects(
    identifier: str,
    x: int,
    y: int,
    dir: int,
    radius: int,
    is_boosting: bool,
    color: str,
    env: slimevolley_boost_env.SlimeVolleyBoostEnv,
    resolution: int = 30,
):
    objects = []
    points = []
    for i in range(resolution + 1):
        ang = math.pi - math.pi * i / resolution
        points.append(
            (to_x(math.cos(ang) * radius + x), to_y(math.sin(ang) * radius + y))
        )

    objects.append(
        Polygon(uuid=f"{identifier}_body", color=color, points=points, depth=-1)
    )

    if is_boosting:

        boost_points = []
        for i in range(resolution + 1):
            ang = math.pi - math.pi * i / resolution
            boost_points.append(
                (
                    to_x(math.cos(ang) * radius * 1.5 + x),
                    to_y(math.sin(ang) * radius * 1.5 + y),
                )
            )
        objects.append(
            Polygon(
                uuid=f"{identifier}_body_boost",
                color="#FFFF00",  # Bright yellow for high contrast with both blue and red
                points=boost_points,
                depth=-2,
            )
        )

    # Eyes that track the ball!
    angle = math.pi * 60 / 180
    if dir == 1:
        angle = math.pi * 120 / 180

    c = math.cos(angle)
    s = math.sin(angle)
    ballX = env.game.ball.x - (x + (0.6) * radius * c)
    ballY = env.game.ball.y - (y + (0.6) * radius * s)
    dist = math.sqrt(ballX * ballX + ballY * ballY)
    eyeX = ballX / dist
    eyeY = ballY / dist

    pupil = Circle(
        uuid=f"{identifier}_eye_pupil",
        x=to_x(x + (0.6) * radius * c + eyeX * 0.15 * radius),
        y=to_y(y + (0.6) * radius * s + eyeY * 0.15 * radius),
        color="#000000",
        radius=radius * 2,
        depth=2,
    )

    eye_white = Circle(
        uuid=f"{identifier}_eye_white",
        x=to_x(x + (0.6) * radius * c),
        y=to_y(y + (0.6) * radius * s),
        color="#FFFFFF",
        radius=radius * 4,
        depth=1,
    )

    objects.extend([eye_white, pupil])

    return objects


class SlimeVBEnvIG(slimevolley_boost_env.SlimeVolleyBoostEnv):
    def render(self):
        assert self.render_mode == "interactive-gym"
        return slime_volleyball_env_to_rendering(self)


env = SlimeVBEnvIG(
    config={"human_inputs": False, "seed": 42}, render_mode="interactive-gym"
)
