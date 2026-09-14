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
 * KillAura.F: синхронность ударов (порт Hawk FightSynchronized).
 * Живой жмёт в случайный момент между пакетами движения, а аура
 * (включая SpookyTime-подобные) бьёт в том же тике, что крутится:
 * удар &lt;6 мс после пакета движения в &gt;90% случаев из 10.
 * Пороги Hawk один в один, время — нанотаймер (миллисов мало).
 */
public final class KillAuraF extends Check {

    private static final class State {
        long prevMove;
        long lastMove;
        long lastAttack;
        int sync;
        int total;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public KillAuraF(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "F", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        long now = System.nanoTime();
        if (state.lastAttack > 0) {
            double moveToAttack = (state.lastAttack - state.prevMove) / 1e6;
            double attackToMove = (now - state.lastAttack) / 1e6;
            if (moveToAttack >= 0 && moveToAttack + attackToMove >= 40) {
                state.total++;
                if (moveToAttack < 6) {
                    state.sync++;
                }
                if (state.total >= 10) {
                    if (state.sync / (double) state.total > 0.9) {
                        flag(plugin.getDataManager().get(player), "sync");
                    }
                    state.sync = 0;
                    state.total = 0;
                }
            }
        }
        state.prevMove = state.lastMove;
        state.lastMove = now;
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        states.computeIfAbsent(attacker.getUniqueId(), key -> new State())
                .lastAttack = System.nanoTime();
    }
}
