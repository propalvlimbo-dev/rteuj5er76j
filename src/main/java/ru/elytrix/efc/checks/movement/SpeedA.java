package ru.elytrix.efc.checks.movement;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.potion.PotionEffect;
import org.bukkit.potion.PotionEffectType;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Speed.A: средняя скорость по земле за ~секунду.
 * Спринт-прыжки дают ~7.5 б/с, порог 9.5 + бонус за эффект скорости.
 * Меряем среднюю, а не пики — откидывание и микро-лаги не флагают.
 */
public final class SpeedA extends Check {

    private static final class State {
        double distance;
        long windowStart;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public SpeedA(ElytrixFuckCheats plugin) {
        super(plugin, "Speed", "A", Category.MOVEMENT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        if (!player.isOnGround() || player.isGliding() || player.isInsideVehicle() || player.isInWater()) {
            reset(state);
            return;
        }
        double dx = event.getTo().getX() - event.getFrom().getX();
        double dz = event.getTo().getZ() - event.getFrom().getZ();
        double step = Math.sqrt(dx * dx + dz * dz);
        if (step > 8) {
            // Рывок телепорта/бага — не скорость, пропускаем окно.
            reset(state);
            return;
        }
        long now = System.currentTimeMillis();
        if (state.windowStart == 0) {
            state.windowStart = now;
        }
        state.distance += step;
        long elapsed = now - state.windowStart;
        if (elapsed < 900) {
            return;
        }
        double blocksPerSecond = state.distance / (elapsed / 1000.0);
        double max = cfg("max-bps", 9.5) + speedBonus(player);
        reset(state);
        if (blocksPerSecond > max) {
            flag(plugin.getDataManager().get(player), String.format("%.1f b/s", blocksPerSecond));
        }
    }

    private static void reset(State state) {
        state.distance = 0;
        state.windowStart = 0;
    }

    private static double speedBonus(Player player) {
        for (PotionEffect effect : player.getActivePotionEffects()) {
            if (effect.getType() == PotionEffectType.SPEED) {
                return (effect.getAmplifier() + 1) * 2.2;
            }
        }
        return 0;
    }
}
