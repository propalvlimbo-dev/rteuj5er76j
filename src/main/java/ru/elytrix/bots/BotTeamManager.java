package ru.elytrix.bots;

import net.luckperms.api.LuckPerms;
import net.luckperms.api.LuckPermsProvider;
import net.luckperms.api.model.group.Group;
import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.scoreboard.Scoreboard;
import org.bukkit.scoreboard.Team;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

final class BotTeamManager {
    private final List<Team> created = new ArrayList<>();
    private static final List<String> ORDER = List.of("owner","eternity","elder","dragon","immortal","wither","griefer","prime","lite","default");

    Style add(String name, String groupName, String fallbackSuffix) {
        Scoreboard board = Bukkit.getScoreboardManager().getMainScoreboard();
        int rank = ORDER.indexOf(groupName.toLowerCase(Locale.ROOT));
        if (rank < 0) rank = ORDER.size();
        // z-prefix prevents unknown packet players from jumping above TAB-managed real players.
        String id = String.format("zEB%02d%08x", rank, name.hashCode());
        if (id.length() > 16) id = id.substring(0, 16);
        Team old = board.getTeam(id); if (old != null) old.unregister();
        Team team = board.registerNewTeam(id);
        String prefix = "", suffix = "";
        if (Bukkit.getPluginManager().isPluginEnabled("LuckPerms")) {
            LuckPerms lp = LuckPermsProvider.get();
            Group group = lp.getGroupManager().getGroup(groupName);
            if (group != null) {
                String p = group.getCachedData().getMetaData().getPrefix();
                String s = group.getCachedData().getMetaData().getSuffix();
                prefix = p == null ? "" : colors(p);
                suffix = s == null ? "" : colors(s);
            }
        }
        if (suffix.isEmpty()) suffix = colors(fallbackSuffix);
        team.setPrefix(prefix);
        team.setColor(ChatColor.GRAY);
        team.setSuffix(suffix);
        team.setOption(Team.Option.NAME_TAG_VISIBILITY, Team.OptionStatus.ALWAYS);
        team.addEntry(name);
        created.add(team);
        return new Style(prefix, suffix);
    }

    record Style(String prefix, String suffix) {}

    void clear() {
        for (Team team : created) try { team.unregister(); } catch (IllegalStateException ignored) {}
        created.clear();
    }
    private static String colors(String value) {
        // Legacy RGB format supported by Minecraft 1.16: &#RRGGBB -> §x§R§R§G§G§B§B.
        StringBuilder out=new StringBuilder();
        for(int i=0;i<value.length();i++) {
            if(i+7<value.length()&&value.charAt(i)=='&'&&value.charAt(i+1)=='#') {
                String hex=value.substring(i+2,i+8);
                if(hex.matches("[0-9a-fA-F]{6}")) {
                    out.append('§').append('x');
                    for(char c:hex.toCharArray()) out.append('§').append(c);
                    i+=7; continue;
                }
            }
            out.append(value.charAt(i));
        }
        return ChatColor.translateAlternateColorCodes('&',out.toString());
    }
}
