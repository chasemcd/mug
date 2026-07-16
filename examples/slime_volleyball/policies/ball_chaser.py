"""Ball-chasing heuristic policy for Slime Volleyball."""

from __future__ import annotations

from mug.configurations.configuration_constants import HeuristicPolicy

# Action indices (screen-absolute with human_inputs=True; see
# examples/slime_volleyball/slime_volleyball_constants.py)
NOOP = 0
LEFT = 1
UPLEFT = 2
UP = 3
UPRIGHT = 4
RIGHT = 5


class BallChaser(HeuristicPolicy):
    """Chase the ball's predicted landing spot and jump into close balls."""

    # Court geometry: x spans [-24, 24] with the fence at x=0. Agents are
    # confined to their half (right agent: roughly x in [2, 22.5]).
    HOME_X = 12.0  # Resting position at the middle of our half
    LOOKAHEAD = 0.15  # Seconds of ball velocity to lead the chase target by
    DEADZONE = 0.7  # Don't move when within this distance of the target
    JUMP_RANGE = 3.0  # Jump when the ball is within this horizontal distance
    JUMP_HEIGHT = 6.0  # ...and below this height, descending

    def compute_action(self, env, agent_id):
        """Select an action for `agent_id` given the live env instance."""
        state = env.get_state()
        on_right_side = "right" in str(agent_id)
        side = 1.0 if on_right_side else -1.0

        my_x = state["agent_right_x" if on_right_side else "agent_left_x"]
        ball_x = state["ball_pos_x"]
        ball_y = state["ball_pos_y"]
        ball_vx = state["ball_vel_x"]
        ball_vy = state["ball_vel_y"]

        # Lead the ball slightly so we meet it instead of trailing it.
        predicted_x = ball_x + ball_vx * self.LOOKAHEAD

        # Chase the ball when it's on (or heading to) our side; otherwise
        # return to a home position in the middle of our half.
        ball_incoming = predicted_x * side > 0
        target_x = predicted_x if ball_incoming else self.HOME_X * side

        dx = target_x - my_x
        move = NOOP
        if dx > self.DEADZONE:
            move = RIGHT
        elif dx < -self.DEADZONE:
            move = LEFT

        # Jump when the ball is dropping in close.
        ball_close = abs(ball_x - my_x) < self.JUMP_RANGE
        ball_dropping = ball_vy < 0 and ball_y < self.JUMP_HEIGHT
        if ball_incoming and ball_close and ball_dropping:
            if move == RIGHT:
                return UPRIGHT
            if move == LEFT:
                return UPLEFT
            return UP

        return move
