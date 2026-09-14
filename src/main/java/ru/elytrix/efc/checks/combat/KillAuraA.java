package ru.elytrix.efc.checks.combat;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * KillAura.A: доводка-рывок — разворот за один пакет + удар сразу после.
 * Порог 200° за пакет (4000°/с): резкие, но человеческие флики не достают.
 * Окно 120 мс: случайный хит после рывка прощается, системный — нет.
 */
public final class KillAuraA extends Check {

    private static final class State {
        float lastYaw;
        float lastPitch;
        boolean has;
        long lastSnap;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public KillAuraA(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "A", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        State state = states.computeIfAbsent(event.getPlayer().getUniqueId(), key -> new State());
        float yaw = event.getTo().getYaw();
        float pitch = event.getTo().getPitch();
        if (!state.has) {
            state.has = true;
            state.lastYaw = yaw;
            state.lastPitch = pitch;
            return;
        }
        double delta = Math.abs(yaw - state.lastYaw) % 360;
        if (delta > 180) {
            delta = 360 - delta;
        }
        if (delta > cfg("snap-degrees", 200)) {
            state.lastSnap = System.currentTimeMillis();
        }
        state.lastYaw = yaw;
        state.lastPitch = pitch;
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        State state = states.get(attacker.getUniqueId());
        if (state == null) {
            return;
        }
        if (System.currentTimeMillis() - state.lastSnap < cfg("hit-window-ms", 120)) {
            flag(plugin.getDataManager().get(attacker), "snap");
        }
    }
}
