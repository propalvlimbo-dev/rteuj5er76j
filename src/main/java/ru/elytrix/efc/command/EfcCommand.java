package ru.elytrix.efc.command;

import java.util.ArrayList;
import java.util.List;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.command.TabCompleter;
import org.bukkit.entity.Player;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.checks.combat.AimF;
import ru.elytrix.efc.data.PlayerData;

/**
 * /efc — info, vl, debug, reload. Минимализм: только нужное админу.
 */
public final class EfcCommand implements CommandExecutor, TabCompleter {

    private final ElytrixFuckCheats plugin;

    public EfcCommand(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!sender.hasPermission("efc.admin")) {
            sender.sendMessage("§cНет прав.");
            return true;
        }
        if (args.length == 0 || args[0].equalsIgnoreCase("help")) {
            sender.sendMessage("§e/efc info <ник> §7— нарушения игрока");
            sender.sendMessage("§e/efc vl <ник> <сброс|число> §7— выставить VL");
            sender.sendMessage("§e/efc debug <ник> §7— счётчики событий боя");
            sender.sendMessage("§e/efc reload §7— перезагрузить конфиг");
            return true;
        }
        if (args[0].equalsIgnoreCase("reload")) {
            plugin.reloadEfcConfig();
            sender.sendMessage("§a[EFC] Конфиг перезагружен.");
            return true;
        }
        if (args[0].equalsIgnoreCase("debug") && sender.hasPermission("efc.admin")) {
            if (args.length < 2) {
                sender.sendMessage("§c/efc debug <ник>");
                return true;
            }
            Player target = plugin.getServer().getPlayerExact(args[1]);
            if (target == null) {
                sender.sendMessage("§cИгрок не в сети.");
                return true;
            }
            sender.sendMessage("§e[EFC] §fСобытия §e" + target.getName() + "§f: "
                    + plugin.getDebugCounters().report(target.getUniqueId()));
            Check aimF = plugin.getCheckManager().get("Aim.F");
            sender.sendMessage("§e[EFC] §fПрицел: §e" + (aimF instanceof AimF
                    ? ((AimF) aimF).status(target.getUniqueId()) : "-"));
            return true;
        }
        if (args[0].equalsIgnoreCase("info")) {
            if (args.length < 2) {
                sender.sendMessage("§c/efc info <ник>");
                return true;
            }
            Player target = plugin.getServer().getPlayerExact(args[1]);
            if (target == null) {
                sender.sendMessage("§cИгрок не в сети.");
                return true;
            }
            PlayerData data = plugin.getDataManager().get(target);
            sender.sendMessage("§e[EFC] §f" + target.getName()
                    + " §7пинг " + data.getPing() + " §7версия " + data.getClientVersion());
            boolean empty = true;
            for (Check check : plugin.getCheckManager().getChecks()) {
                double vl = data.getVl(check.id());
                if (vl > 0) {
                    empty = false;
                    sender.sendMessage("§7- §f" + check.id() + " §eVL " + Math.round(vl));
                }
            }
            if (empty) {
                sender.sendMessage("§aЧист.");
            }
            return true;
        }
        if (args[0].equalsIgnoreCase("vl")) {
            if (args.length < 3) {
                sender.sendMessage("§c/efc vl <ник> <сброс|число>");
                return true;
            }
            Player target = plugin.getServer().getPlayerExact(args[1]);
            if (target == null) {
                sender.sendMessage("§cИгрок не в сети.");
                return true;
            }
            PlayerData data = plugin.getDataManager().get(target);
            if (args[2].equalsIgnoreCase("сброс")) {
                data.resetAll();
                sender.sendMessage("§a[EFC] VL сброшен.");
            } else {
                try {
                    data.setAll(Double.parseDouble(args[2]));
                    sender.sendMessage("§a[EFC] VL выставлен.");
                } catch (NumberFormatException bad) {
                    sender.sendMessage("§cЧисло или «сброс».");
                }
            }
            return true;
        }
        sender.sendMessage("§c/efc help");
        return true;
    }

    @Override
    public List<String> onTabComplete(CommandSender sender, Command command,
            String alias, String[] args) {
        List<String> out = new ArrayList<>();
        if (!sender.hasPermission("efc.admin")) {
            return out;
        }
        if (args.length == 1) {
            for (String sub : new String[] {"info", "vl", "debug", "reload"}) {
                if (sub.startsWith(args[0].toLowerCase())) {
                    out.add(sub);
                }
            }
        }
        return out;
    }
}
