package ru.elytrix.efc.checks.combat;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import kireiko.dev.millennium.math.Euler;
import kireiko.dev.millennium.math.Statistics;
import kireiko.dev.millennium.vectors.Vec2f;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Aim.H: MX-Project AimSmoothCheck (Unlicense), логика 1:1.
 * Стек из 20 углов поворота (оригинальный MX Euler + Vec2f, mod 90).
 * Три подряд нулевые первые разности (оригинальный MX Statistics) —
 * невалидное сглаживание аима.
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
        double angle = Euler.getAngleInDegrees(new Vec2f(dx, dy)) % 90.0D;
        State state = states.computeIfAbsent(event.getPlayer().getUniqueId(), key -> new State());
        if ((ady > 1.5 && adx > 0.32) || adx > 1.5) {
            state.stack.add(angle);
        }
        if (state.stack.size() >= 20) {
            List<Float> jiff = Statistics.getJiffDelta(state.stack, 1);
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
