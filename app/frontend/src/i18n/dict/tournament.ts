import type {Bundle} from '../types';

export const tournament: Bundle = {
  en: {
    // Empty state
    'tournament.empty':
      'Tournament matchups appear here after the ranking node runs.',

    // Leaderboard
    'tournament.leaderboard': 'Leaderboard',
    'tournament.winLossTitle': '{wins} wins / {losses} losses',

    // Matchups
    'tournament.matchups': 'Matchups',
    'tournament.iter': 'Iter {n}',
    'tournament.matchResult': 'Match result',
    'tournament.winner': 'Winner',
    'tournament.runnerUp': 'Runner-up',
    'tournament.winnerEloDelta': '+{delta} Elo',
    'tournament.loserEloDelta': '{delta} Elo',

    // Elo trajectory chart
    'tournament.chart.title': 'Elo trajectories',
    'tournament.chart.summary': 'top {count} · {matches} matches',
    'tournament.chart.ariaLabel': 'Elo trajectory chart',
    'tournament.chart.xAxis': 'match index →',
  },
  he: {
    // Empty state
    'tournament.empty': 'מפגשי הטורניר יופיעו כאן לאחר שצומת הדירוג ירוץ.',

    // Leaderboard
    'tournament.leaderboard': 'טבלת מובילים',
    'tournament.winLossTitle': '{wins} ניצחונות / {losses} הפסדים',

    // Matchups
    'tournament.matchups': 'מפגשים',
    'tournament.iter': 'איטרציה {n}',
    'tournament.matchResult': 'תוצאת מפגש',
    'tournament.winner': 'מנצח',
    'tournament.runnerUp': 'מקום שני',
    'tournament.winnerEloDelta': '+{delta} Elo',
    'tournament.loserEloDelta': '{delta} Elo',

    // Elo trajectory chart
    'tournament.chart.title': 'מסלולי Elo',
    'tournament.chart.summary': 'מובילים {count} · {matches} מפגשים',
    'tournament.chart.ariaLabel': 'תרשים מסלולי Elo',
    'tournament.chart.xAxis': 'אינדקס מפגש ←',
  },
};
