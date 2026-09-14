package ru.elytrix.efc.checks.combat;

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
 * Aim.A: GCD/modulo-тест ротации (математика Frequency AimAssistE / NESS AimbotGCD).
 * Делим текущую и прошлую дельты на их НОД и смотрим остаток от деления:
 * у живой мыши константа одна, у аима — прыгает. Пороги 90 / 0.1 — оригинал.
 */
public final class AimA extends Check {

    private static final double MODULO_THRESHOLD = 90.0;
    private static final double LINEAR_THRESHOLD = 0.1;

    private static final class State {
        double lastDeltaYaw;
        double lastDeltaPitch;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public AimA(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        double deltaYaw = Math.abs(event.getTo().getYaw() - event.getFrom().getYaw());
        double deltaPitch = Math.abs(event.getTo().getPitch() - event.getFrom().getPitch());

        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        double lastYaw = state.lastDeltaYaw;
        double lastPitch = state.lastDeltaPitch;
        double divisorYaw = gcdRational(deltaYaw, lastYaw);
        double divisorPitch = gcdRational(deltaPitch, lastPitch);
        state.lastDeltaYaw = deltaYaw;
        state.lastDeltaPitch = deltaPitch;

        if (deltaYaw <= 0 || deltaPitch <= 0 || deltaYaw >= 20 || deltaPitch >= 20) {
            return;
        }
        if (divisorYaw == 0 || divisorPitch == 0 || lastYaw == 0 || lastPitch == 0) {
            return;
        }
        double currentX = deltaYaw / divisorYaw;
        double currentY = deltaPitch / divisorPitch;
        double previousX = lastYaw / divisorYaw;
        double previousY = lastPitch / divisorPitch;
        if (previousX == 0 || previousY == 0) {
            return;
        }
        double moduloX = currentX % previousX;
        double moduloY = currentY % previousY;
        double floorX = Math.abs(Math.floor(moduloX) - moduloX);
        double floorY = Math.abs(Math.floor(moduloY) - moduloY);

        boolean invalidX = moduloX > MODULO_THRESHOLD && floorX > LINEAR_THRESHOLD;
        boolean invalidY = moduloY > MODULO_THRESHOLD && floorY > LINEAR_THRESHOLD;
        if (invalidX && invalidY) {
            flag(plugin.getDataManager().get(player), "modulo");
        }
    }

    /** НОД для дробей с допуском на float-шум (NESS MathUtils.gcdRational). */
    private static double gcdRational(double a, double b) {
        if (a < 0.001) {
            return b;
        } else if (b < 0.001) {
            return a;
        }
        int quotient = getIntQuotient(b, a);
        double remainder = ((b / a) - quotient) * a;
        if (Math.abs(remainder) < Math.max(a, b) * 1e-3) {
            remainder = 0;
        }
        return gcdRational(remainder, a);
    }

    private static int getIntQuotient(double dividend, double divisor) {
        double ans = dividend / divisor;
        double error = Math.max(dividend, divisor) * 1e-3;
        return (int) (ans + error);
    }
}
