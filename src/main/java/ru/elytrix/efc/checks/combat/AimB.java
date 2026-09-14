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
 * Aim.B: стабильность НОД питча (математика Hawk AimbotPrecision).
 * Hawk специально использует питч: yaw на высоких FPS даёт ложные.
 * Окно 10 семплов, игнор резких движений и взгляда в зенит.
 * Плюс наш гейт: оцениваем только в бою (удар в последние 3 сек).
 */
public final class AimB extends Check {

    private static final class State {
        final List<Float> samples = new ArrayList<>();
        float lastGcd;
        boolean hasGcd;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public AimB(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "B", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());

        float deltaPitch = event.getTo().getPitch() - event.getFrom().getPitch();
        if (deltaPitch != 0 && Math.abs(deltaPitch) <= 0.96f && Math.abs(event.getTo().getPitch()) != 90) {
            state.samples.add(Math.abs(deltaPitch));
        }
        if (state.samples.size() < 10) {
            return;
        }
        float gcd = gcdRational(state.samples);
        float diff = Math.abs(gcd - (state.hasGcd ? state.lastGcd : gcd));
        if (diff > 0.001f && state.hasGcd && state.lastGcd > 0.001f) {
            // Повтор с прошлым НОД: 10 семплов могло не хватить для того же НОД.
            state.samples.add(state.lastGcd);
            gcd = gcdRational(state.samples);
        }
        state.samples.clear();
        state.lastGcd = gcd;
        state.hasGcd = true;

        if (gcd < 0.00001f) {
            long now = System.currentTimeMillis();
            if (now - plugin.getDataManager().get(player).getLastAttack() > 3000) {
                return;
            }
            flag(plugin.getDataManager().get(player), "unsolvable");
        }
    }

    /** НОД для дробей (Hawk MathPlus.gcdRational). */
    private static float gcdRational(float a, float b) {
        if (a == 0) {
            return b;
        }
        int quotient = getIntQuotient(b, a);
        float remainder = ((b / a) - quotient) * a;
        if (Math.abs(remainder) < Math.max(a, b) * 1e-3f) {
            remainder = 0;
        }
        return gcdRational(remainder, a);
    }

    private static float gcdRational(List<Float> numbers) {
        float result = numbers.get(0);
        for (int i = 1; i < numbers.size(); i++) {
            result = gcdRational(numbers.get(i), result);
            if (result < 1e-7f) {
                return 0;
            }
        }
        return result;
    }

    private static int getIntQuotient(float dividend, float divisor) {
        float ans = dividend / divisor;
        float error = Math.max(dividend, divisor) * 1e-3f;
        return (int) (ans + error);
    }
}
