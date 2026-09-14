package ru.elytrix.efc.command;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.bukkit.ChatColor;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.command.TabCompleter;
import org.bukkit.entity.Player;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.data.PlayerData;

/** /efc — alerts, verbose, info, exempt, reload, check(скоро). */
public final class EfcCommand implements CommandExecutor, TabCompleter {

    private final ElytrixFuckCheats plugin;

    public EfcCommand(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0) {
            sendHelp(sender);
            return true;
        }
        switch (args[0].toLowerCase()) {
            case "alerts":
                return handleAlerts(sender);
            case "verbose":
                return handleVerbose(sender);
            case "reload":
                return handleReload(sender);
            case "info":
                return handleInfo(sender, args);
            case "exempt":
                return handleExempt(sender, args);
            case "check":
                sender.sendMessage(color("&8[&cEFC&8] &7Ручные проверки — со второго билда."));
                return true;
            default:
                sendHelp(sender);
                return true;
        }
    }

    private boolean handleAlerts(CommandSender sender) {
        if (!(sender instanceof Player)) {
            sender.sendMessage(color("&cТолько для игроков."));
            return true;
        }
        if (!sender.hasPermission("efc.alerts")) {
            sender.sendMessage(color("&cНет прав."));
            return true;
        }
        boolean on = plugin.getAlertManager().toggleAlerts((Player) sender);
        sender.sendMessage(color("&8[&cEFC&8] &7Алерты: " + (on ? "&aВКЛ" : "&cВЫКЛ")));
        return true;
    }

    private boolean handleVerbose(CommandSender sender) {
        if (!(sender instanceof Player)) {
            sender.sendMessage(color("&cТолько для игроков."));
            return true;
        }
        if (!sender.hasPermission("efc.admin")) {
            sender.sendMessage(color("&cНет прав."));
            return true;
        }
        boolean on = plugin.getAlertManager().toggleVerbose((Player) sender);
        sender.sendMessage(color("&8[&cEFC&8] &7Verbose: " + (on ? "&aВКЛ" : "&cВЫКЛ")));
        return true;
    }

    private boolean handleReload(CommandSender sender) {
        if (!sender.hasPermission("efc.admin")) {
            sender.sendMessage(color("&cНет прав."));
            return true;
        }
        plugin.getConfigManager().reload();
        sender.sendMessage(color("&8[&cEFC&8] &aКонфиг перезагружен."));
        return true;
    }

    private boolean handleInfo(CommandSender sender, String[] args) {
        if (!sender.hasPermission("efc.alerts")) {
            sender.sendMessage(color("&cНет прав."));
            return true;
        }
        if (args.length < 2) {
            sender.sendMessage(color("&cИспользование: /efc info <ник>"));
            return true;
        }
        Player target = plugin.getServer().getPlayerExact(args[1]);
        if (target == null) {
            sender.sendMessage(color("&cИгрок не в сети."));
            return true;
        }
        PlayerData data = plugin.getDataManager().get(target);
        sender.sendMessage(color("&8[&cEFC&8] &7VL игрока &e" + target.getName() + "&7:"));
        boolean empty = true;
        for (Map.Entry<String, Double> entry : data.getVlSnapshot().entrySet()) {
            if (entry.getValue() > 0) {
                empty = false;
                sender.sendMessage(color(" &8- &e" + entry.getKey() + " &7VL: &c"
                        + Math.round(entry.getValue())));
            }
        }
        if (empty) {
            sender.sendMessage(color(" &7Чист, нарушений нет."));
        }
        return true;
    }

    private boolean handleExempt(CommandSender sender, String[] args) {
        if (!sender.hasPermission("efc.admin")) {
            sender.sendMessage(color("&cНет прав."));
            return true;
        }
        if (args.length < 3) {
            sender.sendMessage(color("&cИспользование: /efc exempt <ник> <секунд>"));
            return true;
        }
        Player target = plugin.getServer().getPlayerExact(args[1]);
        if (target == null) {
            sender.sendMessage(color("&cИгрок не в сети."));
            return true;
        }
        long seconds;
        try {
            seconds = Long.parseLong(args[2]);
        } catch (NumberFormatException e) {
            sender.sendMessage(color("&cСекунды — числом."));
            return true;
        }
        plugin.getExemptionManager().addTimedBypass(target.getUniqueId(), seconds);
        sender.sendMessage(color("&8[&cEFC&8] &a" + target.getName()
                + " &7освобождён от проверок на &e" + seconds + " &7сек."));
        return true;
    }

    private void sendHelp(CommandSender sender) {
        sender.sendMessage(color("&8[&cEFC&8] &7ElytrixFuckCheats v"
                + plugin.getDescription().getVersion()));
        sender.sendMessage(color(" &e/efc alerts &8- &7алерты себе"));
        sender.sendMessage(color(" &e/efc verbose &8- &7дебаг-флаги"));
        sender.sendMessage(color(" &e/efc info <ник> &8- &7VL игрока"));
        sender.sendMessage(color(" &e/efc exempt <ник> <сек> &8- &7временный байпас"));
        sender.sendMessage(color(" &e/efc reload &8- &7перезагрузка конфига"));
    }

    private String color(String text) {
        return ChatColor.translateAlternateColorCodes('&', text);
    }

    @Override
    public List<String> onTabComplete(CommandSender sender, Command command, String alias, String[] args) {
        if (args.length == 1) {
            List<String> subs = new ArrayList<>(Arrays.asList(
                    "alerts", "verbose", "info", "exempt", "reload", "check"));
            subs.removeIf(s -> !s.startsWith(args[0].toLowerCase()));
            return subs;
        }
        if (args.length == 2 && (args[0].equalsIgnoreCase("info") || args[0].equalsIgnoreCase("exempt"))) {
            List<String> names = new ArrayList<>();
            for (Player player : plugin.getServer().getOnlinePlayers()) {
                if (player.getName().toLowerCase().startsWith(args[1].toLowerCase())) {
                    names.add(player.getName());
                }
            }
            return names;
        }
        return Collections.emptyList();
    }
}
