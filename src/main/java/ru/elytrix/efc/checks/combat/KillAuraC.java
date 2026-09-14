package ru.elytrix.efc.checks.combat;

import java.util.ArrayDeque;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.util.DamageUtil;

/**
 * KillAura.C: мульти-аура — удары по 3+ разным целям за 300 мс.
 * Живой игрок так быстро цели не меняет. Свип-атака по толпе даёт
 * редкие флаги, но VL с затуханием их прощает.
 */
public final class KillAuraC extends Check {

    private static final class Hit {
        final UUID victim;
        final long time;

        Hit(UUID victim, long time) {
            this.victim = victim;
            this.time = time;
        }
    }

    private final Map<UUID, ArrayDeque<Hit>> hits = new ConcurrentHashMap<>();

    public KillAuraC(ElytrixFuckCheats plugin) {
        super(plugin, "KillAura", "C", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        hits.remove(uuid);
    }

    @EventHandler
    public void onDamage(EntityDamageByEntityEvent event) {
        Player attacker = DamageUtil.meleeAttacker(event);
        if (attacker == null) {
            return;
        }
        long now = System.currentTimeMillis();
        java.util.UUID victimId = DamageUtil.victimId(event);
        if (victimId == null) {
            return;
        }
        ArrayDeque<Hit> recent = hits.computeIfAbsent(attacker.getUniqueId(), key -> new ArrayDeque<>());
        recent.addLast(new Hit(victimId, now));
        while (!recent.isEmpty() && now - recent.peekFirst().time > 300) {
            recent.pollFirst();
        }
        Set<UUID> victims = new HashSet<>();
        for (Hit hit : recent) {
            victims.add(hit.victim);
        }
        if (victims.size() >= 3) {
            recent.clear();
            flag(plugin.getDataManager().get(attacker), "multi " + victims.size());
        }
    }
}
