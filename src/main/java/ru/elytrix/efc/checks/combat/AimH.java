package ru.elytrix.efc.checks.combat;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Aim.H: портировано из MX-Project AimSmoothCheck (Unlicense).
 * Стек из 20 углов поворота (atan2 по дельтам, mod 90).
 * Три подряд нулевые первые разности — невалидное сглаживание аима.
 */
public final class AimH extends Check {

    private static final class State {
        final List<Double> stack = new ArrayList<>();
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public AimH(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "H", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        float dx = wrap(event.getTo().getYaw() - event.getFrom().getYaw());
        float dy = event.getTo().getPitch() - event.getFrom().getPitch();
        if (dx == 0.0F && dy == 0.0F) {
            return;
        }
        float adx = Math.abs(dx);
        float ady = Math.abs(dy);
        double angle = angleInDegrees(dx, dy) % 90.0D;
        State state = states.computeIfAbsent(event.getPlayer().getUniqueId(), key -> new State());
        if ((ady > 1.5 && adx > 0.32) || adx > 1.5) {
            state.stack.add(angle);
        }
        if (state.stack.size() >= 20) {
            List<Float> jiff = jiffDelta(state.stack, 1);
            float prev = 999.0F;
            float prePrev = 999.0F;
            for (float value : jiff) {
                if (value == 0.0F && prev == 0.0F && prePrev == 0.0F) {
                    flag(plugin.getDataManager().get(event.getPlayer()), "smooth");
                    break;
                }
                prePrev = prev;
                prev = value;
            }
            state.stack.clear();
        }
    }

    /** MX Euler.getAngleInDegrees. */
    private static double angleInDegrees(float x, float y) {
        double degrees = Math.toDegrees(Math.atan2(x, y));
        if (degrees < 0) {
            degrees += 360.0D;
        }
        return degrees;
    }

    /** MX Statistics.getJiffDelta. */
    private static List<Float> jiffDelta(List<Double> data, int depth) {
        List<Float> result = new ArrayList<>();
        for (Double value : data) {
            result.add(value.floatValue());
        }
        for (int i = 0; i < depth; i++) {
            List<Float> calculate = new ArrayList<>();
            float old = Float.MIN_VALUE;
            for (float value : result) {
                if (old == Float.MIN_VALUE) {
                    old = value;
                    continue;
                }
                calculate.add(Math.abs(Math.abs(value) - Math.abs(old)));
                old = value;
            }
            result = new ArrayList<>(calculate);
        }
        return result;
    }

    private static float wrap(float yaw) {
        while (yaw > 180.0F) {
            yaw -= 360.0F;
        }
        while (yaw < -180.0F) {
            yaw += 360.0F;
        }
        return yaw;
    }
}
