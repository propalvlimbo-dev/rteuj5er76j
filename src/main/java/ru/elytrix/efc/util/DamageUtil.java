package ru.elytrix.efc.util;

import java.lang.reflect.Method;
import java.util.UUID;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.entity.DamageCause;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.EntityDamageEvent;
import ru.elytrix.efc.packet.PacketManager;

/**
 * Доступ к методам damage-событий через рефлексию + пинг + лимиты рича.
 * Некоторые форки (замечен ShieldSpigot) ломают иерархию событий:
 * унаследованные getCause/getDamage/getEntity отсутствуют и прямой вызов
 * падает с NoSuchMethodError. Здесь всё с проверками и фолбэками.
 */
public final class DamageUtil {

    private static final Method GET_CAUSE = find(EntityDamageByEntityEvent.class, "getCause");
    private static final Method GET_DAMAGE = find(EntityDamageEvent.class, "getDamage");
    private static final Method GET_ENTITY = find(EntityDamageEvent.class, "getEntity");
    private static final Method GET_DAMAGER = find(EntityDamageByEntityEvent.class, "getDamager");
    private static final Method SET_DAMAGE = findDamage();

    private static Method pingMethod;
    private static Class<?> pingClass;
    private static volatile PacketManager packetManager;

    private DamageUtil() {
    }

    /** Пакетный слой ставит себя сюда, если PacketEvents на сервере. */
    public static void setPacketManager(PacketManager manager) {
        packetManager = manager;
    }

    private static Method find(Class<?> owner, String name) {
        try {
            return owner.getMethod(name);
        } catch (Throwable ignored) {
            return null;
        }
    }

    /** Есть ли рабочий getCause (нет — включаются запасные эвристики). */
    public static boolean hasCause() {
        return GET_CAUSE != null;
    }

    private static Method findDamage() {
        try {
            return EntityDamageEvent.class.getMethod("setDamage", double.class);
        } catch (Throwable ignored) {
            return null;
        }
    }

    /** Есть ли рабочий getDamage (нужен Velocity.A). */
    public static boolean hasDamage() {
        return GET_DAMAGE != null;
    }

    public static DamageCause causeOf(EntityDamageEvent event) {
        if (GET_CAUSE == null) {
            return null;
        }
        try {
            return (DamageCause) GET_CAUSE.invoke(event);
        } catch (Throwable ignored) {
            return null;
        }
    }

    /** Обнулить урон (форки иногда игнорируют cancel). true — вышло. */
    public static boolean setDamage(EntityDamageEvent event, double value) {
        if (SET_DAMAGE == null) {
            return false;
        }
        try {
            SET_DAMAGE.invoke(event, value);
            return true;
        } catch (Throwable ignored) {
            return false;
        }
    }

    public static double damageOf(EntityDamageEvent event) {
        if (GET_DAMAGE == null) {
            return -1;
        }
        try {
            Object value = GET_DAMAGE.invoke(event);
            return value instanceof Number ? ((Number) value).doubleValue() : -1;
        } catch (Throwable ignored) {
            return -1;
        }
    }

    public static Entity entityOf(EntityDamageEvent event) {
        if (GET_ENTITY == null) {
            return null;
        }
        try {
            return (Entity) GET_ENTITY.invoke(event);
        } catch (Throwable ignored) {
            return null;
        }
    }

    public static UUID victimId(EntityDamageEvent event) {
        Entity victim = entityOf(event);
        return victim == null ? null : victim.getUniqueId();
    }

    public static Entity damagerOf(EntityDamageByEntityEvent event) {
        if (GET_DAMAGER == null) {
            return null;
        }
        try {
            return (Entity) GET_DAMAGER.invoke(event);
        } catch (Throwable ignored) {
            return null;
        }
    }

    /** Настоящий удар мечом/рукой (не шипы, магия, стрелы). */
    public static boolean isMelee(EntityDamageByEntityEvent event) {
        DamageCause cause = causeOf(event);
        if (cause == null) {
            // Причина недоступна (кривой форк) — считаем ближним боем любой
            // урон от игрока. Шипы дают редкий шум, VL с затуханием прощает.
            return damagerOf(event) instanceof Player;
        }
        return cause == DamageCause.ENTITY_ATTACK || cause == DamageCause.ENTITY_SWEEP_ATTACK;
    }

    /** Атакующий-игрок ближнего боя, иначе null. */
    public static Player meleeAttacker(EntityDamageByEntityEvent event) {
        if (!isMelee(event)) {
            return null;
        }
        Entity damager = damagerOf(event);
        return damager instanceof Player ? (Player) damager : null;
    }

    /**
     * Пинг: сначала точный от PacketEvents (если слой активен),
     * иначе CraftPlayer.getPing рефлексией (в API 1.16 его нет).
     */
    public static int pingOf(Player player) {
        PacketManager packets = packetManager;
        if (packets != null && packets.isAvailable()) {
            int pePing = packets.ping(player);
            if (pePing >= 0) {
                return Math.min(2000, pePing);
            }
        }
        try {
            if (pingMethod == null || pingClass != player.getClass()) {
                pingClass = player.getClass();
                pingMethod = pingClass.getMethod("getPing");
            }
            Object value = pingMethod.invoke(player);
            int ping = value instanceof Number ? ((Number) value).intValue() : 150;
            return Math.max(0, Math.min(2000, ping));
        } catch (Throwable ignored) {
            pingMethod = null;
            return 150;
        }
    }

    /**
     * Лимит дистанции с компенсацией пинга обоих бойцов (как у всех топов):
     * лагующий честный игрок бьёт «дальше» только на бумаге.
     */
    public static double reachLimit(Player attacker, Entity victim, double base, double perMs, double cap) {
        int total = pingOf(attacker) + (victim instanceof Player ? pingOf((Player) victim) : 0);
        return Math.min(base + total * perMs, cap);
    }

    /**
     * На сколько мс в прошлое перематывать жертву: атакующий целится в то,
     * что видит, а видит он прошлое (пинг обоих пополам + ~100 мс
     * интерполяции сущностей на клиенте).
     */
    public static long rewindDelay(Player attacker, Entity victim) {
        int total = pingOf(attacker) + (victim instanceof Player ? pingOf((Player) victim) : 0);
        return Math.max(0, Math.min(1000, total / 2 + 100));
    }

    /**
     * На сколько мс в прошлое перематывать атакующего: пакет удара летит
     * до сервера половину пинга + квант тика. Без этого глаз врёт на
     * рывках (позиция сервера уже не та, что видел клиент).
     */
    public static long attackerDelay(Player attacker) {
        return Math.max(0, Math.min(500, pingOf(attacker) / 2 + 25));
    }
}
